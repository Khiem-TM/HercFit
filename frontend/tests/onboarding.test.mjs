import { test, before, after, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { initialForm, validateStep, buildOnboardingPayload, authenticatedDestination, todayInVietnam } from '../src/features/onboarding/model.ts'

const athlete = { id:'test-user',email:'synthetic@example.org',fullname:'Athlete',nick_name:null,age:null,personal_info:{},is_onboarding:false }
function ready() {
  const form=initialForm(athlete)
  Object.assign(form,{weight:'68.125',height:'172.5',bodyFat:'0',muscleMass:'30.001',goalType:'fitness',goalTitle:'Khỏe hơn mỗi ngày',startDate:'2026-10-23',targetDate:'2026-12-31',targetWeight:'70',confirmed:true})
  return form
}
test('new and completed users are routed according to the backend completion flag', () => {
  for (const path of ['/','/chat','/onboarding','/auth/callback']) assert.equal(authenticatedDestination(path,false),'/onboarding')
  assert.equal(authenticatedDestination('/onboarding',true),'/chat')
  assert.equal(authenticatedDestination('/chat',true),'/chat')
})
test('start date uses Vietnam local date across the UTC day boundary', () => {
  assert.equal(todayInVietnam(new Date('2026-10-22T18:30:00Z')),'2026-10-23')
})
test('skip optional aggregates by omission, never null or an incomplete object', () => {
  const form=ready(); form.metricsEnabled=false; form.goalEnabled=false
  form.weight='';form.goalTitle='';form.startDate=''
  const payload=buildOnboardingPayload(form,athlete)
  assert.equal('body_metric' in payload,false);assert.equal('goal' in payload,false)
  assert.equal('personal_info' in payload,false)
})
test('payload maps snapshots, discriminated targets and optional zeros correctly', () => {
  const payload=buildOnboardingPayload(ready(),athlete)
  assert.equal(payload.body_metric.body_fat_pct,0)
  assert.deepEqual(payload.goal.targets.weight_kg,{unit:'kg',operator:'eq',value:70,baseline:68.125})
  assert.equal('is_onboarding' in payload,false)
  assert.equal('user_id' in payload,false)
  assert.equal('recorded_at' in payload.body_metric,false)
})
test('unknown measurements are omitted and target does not invent a baseline', () => {
  const form=ready(); form.height='';form.muscleMass='';form.bodyFat=''
  assert.deepEqual(buildOnboardingPayload(form,athlete).body_metric,{weight_kg:68.125})
  form.metricsEnabled=false
  assert.equal('baseline' in buildOnboardingPayload(form,athlete).goal.targets.weight_kg,false)
})
test('all numerical boundaries follow backend precision and positivity', () => {
  for (const value of ['0','-1','NaN','Infinity','10000000','68.1234']) {
    const form=ready();form.weight=value;assert.ok(validateStep(form,1).weight,value)
  }
  for (const value of ['0.001','9999999.999']) {
    const form=ready();form.weight=value;assert.equal(validateStep(form,1).weight,undefined,value)
  }
  for (const value of ['-0.1','100.01','12.123']) {
    const form=ready();form.bodyFat=value;assert.ok(validateStep(form,1).bodyFat,value)
  }
  const form=ready();form.age='28.5';assert.ok(validateStep(form,0).age)
  form.age='121';assert.ok(validateStep(form,0).age)
})
test('name, goal, date order and explicit final confirmation are required when enabled', () => {
  const form=ready();form.fullname='  ';assert.ok(validateStep(form,0).fullname)
  form.goalTitle='';form.targetDate='2026-01-01';assert.ok(validateStep(form,2).goalTitle);assert.ok(validateStep(form,2).targetDate)
  form.startDate='2026-02-30';assert.ok(validateStep(form,2).startDate)
  form.confirmed=false;assert.ok(validateStep(form,3).confirmed)
  assert.throws(()=>buildOnboardingPayload(form,athlete))
})
test('personal_info group merging preserves fields the form does not edit', () => {
  const user={...athlete,personal_info:{activity:{level:'light',sport:'swim'},preferences:{notes:'old',cuisine:'Vietnamese'},other:{keep:true}}}
  const form=ready();form.activity='moderate';form.notes=' New note '
  const payload=buildOnboardingPayload(form,user)
  assert.deepEqual(payload.personal_info,{activity:{level:'moderate',sport:'swim'},preferences:{notes:'New note',cuisine:'Vietnamese'}})
})
const python=fileURLToPath(new URL('../../.venv/bin/python',import.meta.url))
test('generated payloads validate against the actual backend OnboardingInput schema', {skip:!existsSync(python)}, () => {
  const samples=[]
  const form=ready();samples.push(buildOnboardingPayload(form,athlete))
  form.metricsEnabled=false;samples.push(buildOnboardingPayload(form,athlete))
  form.goalEnabled=false;samples.push(buildOnboardingPayload(form,athlete))
  execFileSync(python,['-c','import json,sys; from schemas.user import OnboardingInput; [OnboardingInput.model_validate(p) for p in json.load(sys.stdin)]'],{
    input:JSON.stringify(samples),env:{...process.env,PYTHONPATH:fileURLToPath(new URL('../../backend',import.meta.url))},stdio:['pipe','pipe','pipe'] })
})

let server,auth,useOnboarding
const originalFetch=globalThis.fetch
before(async () => {
  server=await createServer({root:fileURLToPath(new URL('../',import.meta.url)),server:{middlewareMode:true,hmr:false,watch:null},css:{postcss:{plugins:[]}},logLevel:'silent'})
  auth=(await server.ssrLoadModule('/src/composables/useAuth.ts')).useAuth()
  useOnboarding=(await server.ssrLoadModule('/src/composables/useOnboarding.ts')).useOnboarding
})
beforeEach(() => { auth.user.value=structuredClone(athlete);auth.currentGoal.value=null;auth.accessToken.value='synthetic-only' })
after(async () => {globalThis.fetch=originalFetch;await server?.close()})
function auxiliaries(url) {
  if (url==='/api/profile') return Response.json({...athlete,is_onboarding:true})
  if (url==='/api/body-metrics/latest' || url==='/api/goals/current') return new Response('',{status:404})
  throw new Error(`Unexpected URL: ${url}`)
}
test('no write occurs before final explicit confirmation', async () => {
  let count=0;globalThis.fetch=async()=>{ count++;throw new Error('must not submit') }
  const state=useOnboarding();Object.assign(state.form,ready(),{confirmed:false})
  await state.submit();assert.equal(count,0);assert.equal(state.step.value,3);assert.ok(state.errors.value.confirmed)
})
test('unknown write outcome freezes request and retries the identical body/key', async () => {
  const requests=[]
  globalThis.fetch=async(url,init)=>{
    if(url!=='/api/profile/onboarding') return auxiliaries(url)
    requests.push(init)
    if(requests.length===1) throw new TypeError('network failed')
    return Response.json({...athlete,is_onboarding:true})
  }
  const state=useOnboarding();Object.assign(state.form,ready());state.step.value=3
  await state.submit();assert.equal(state.uncertain.value,true);assert.equal(state.locked.value,true)
  state.form.weight='90' // Even a programmatic mutation cannot change an accepted request.
  await state.submit();assert.equal(requests.length,2)
  assert.equal(requests[0].body,requests[1].body)
  assert.equal(requests[0].headers.get('Idempotency-Key'),requests[1].headers.get('Idempotency-Key'))
  assert.equal(auth.user.value.is_onboarding,true)
})
test('definitive validation failure unlocks editing and corrected submission uses a new key', async () => {
  const requests=[]
  globalThis.fetch=async(url,init)=>{
    if(url!=='/api/profile/onboarding') return auxiliaries(url)
    requests.push(init)
    return requests.length===1 ? Response.json({detail:[]},{status:422}) : Response.json({...athlete,is_onboarding:true})
  }
  const state=useOnboarding();Object.assign(state.form,ready());await state.submit()
  assert.equal(state.locked.value,false);state.form.weight='70';await state.submit()
  assert.notEqual(requests[0].headers.get('Idempotency-Key'),requests[1].headers.get('Idempotency-Key'))
})
test('existing active goal is preserved rather than submitted again', () => {
  auth.currentGoal.value={title:'Existing goal'}
  const state=useOnboarding();assert.equal(state.form.goalEnabled,false)
})
test('going back clears confirmation so edited information must be reviewed again', () => {
  const state=useOnboarding();Object.assign(state.form,ready());state.step.value=3
  state.back();assert.equal(state.step.value,2);assert.equal(state.form.confirmed,false)
})
test('double clicking final submission issues exactly one POST', async () => {
  let finish,count=0
  globalThis.fetch=async(url)=>{
    if(url!=='/api/profile/onboarding') return auxiliaries(url)
    count++
    return new Promise(resolve=>{finish=()=>resolve(Response.json({...athlete,is_onboarding:true}))})
  }
  const state=useOnboarding();Object.assign(state.form,ready())
  const first=state.submit();await state.submit();assert.equal(count,1)
  finish();await first;assert.equal(state.submitting.value,false)
})
test('onboarding screen renders the four steps and authenticated profile with accessible fields', async () => {
  const { createSSRApp }=await import('vue')
  const { renderToString }=await import('vue/server-renderer')
  const Page=(await server.ssrLoadModule('/src/views/OnboardingPage.vue')).default
  const html=await renderToString(createSSRApp(Page))
  for(const label of ['Hồ sơ','Số đo','Mục tiêu','Xác nhận','Họ và tên']) {
    assert.ok(html.includes(label),label)
  }
  assert.ok(html.includes('value="Athlete"'))
  assert.ok(html.includes('for="fullname"'))
  assert.ok(html.includes('id="fullname"'))
  assert.ok(html.includes('novalidate'))
})
test('measurement UI exposes the same precision boundaries as backend validation', async () => {
  const { createSSRApp }=await import('vue')
  const { renderToString }=await import('vue/server-renderer')
  const Metrics=(await server.ssrLoadModule('/src/components/onboarding/MetricsStep.vue')).default
  const html=await renderToString(createSSRApp(Metrics,{modelValue:ready(),errors:{}}))
  assert.ok(html.includes('step="0.001"'));assert.ok(html.includes('step="0.01"'))
  assert.ok(html.includes('max="100"'));assert.ok(html.includes('max="9999999.999"'))
  assert.ok(html.includes('id="bodyFat"'))
})
