"""Allowlisted API tools. Input and output types are the backend's actual contracts."""
from dataclasses import dataclass
from typing import Any
from uuid import UUID
from pydantic import BaseModel, Field, TypeAdapter, create_model
from langchain_core.tools import StructuredTool
from schemas.common import InputSchema, Pagination, JsonObjectInput
from schemas.user import UserRead, UserUpdate, OnboardingInput
from schemas.body_metrics import BodyMetricCreate, BodyMetricRead, BodyMetricQuery
from schemas.goal import GoalCreate, GoalRead, GoalUpdateRequest
from schemas.foods import FoodCreate, FoodRead, FoodQuery
from schemas.exercises import ExerciseCreate, ExerciseRead, ExerciseQuery
from schemas.journals import MealCreate, MealReplace, MealRead, TrainingCreate, TrainingReplace, TrainingRead
from schemas.tracking import JournalQuery, DateRangeQuery
from schemas.progress import ProgressRead

class Empty(InputSchema):
    pass

class Resource(InputSchema):
    resource_id: UUID

class VersionedResource(Resource):
    expected_version_id: int = Field(ge=1, strict=True)

@dataclass(frozen=True)
class ToolSpec:
    name: str
    domain: str
    method: str
    path: str
    schema: type[BaseModel]
    output: Any
    description: str
    body: bool = False

    @property
    def write(self):
        return self.method != 'GET'

    def normalize(self, args):
        value = self.schema.model_validate(args)
        # Materialize defaults only for creates, so previews contain the exact
        # timestamps/defaults that will be sent. PATCH/PUT preserve omissions.
        return value.model_dump(mode='json', exclude_unset=self.method != 'POST')

    def request_parts(self, args):
        args = dict(args)
        resource_id = args.pop('resource_id', None)
        path = self.path.format(resource_id=resource_id)
        return path, ({} if self.body else args), (args if self.body else None)

    def as_tool(self):
        async def declaration(**kwargs):
            raise RuntimeError('Tools must execute through the approval-aware adapter')
        return StructuredTool.from_function(coroutine=declaration, name=self.name,
                                            description=self.description, args_schema=self.schema)

REGISTRY: dict[str, ToolSpec] = {}

def add(name, domain, method, path, schema, output, description, body=False):
    REGISTRY[name] = ToolSpec(name, domain, method, '/api' + path, schema, output, description, body)

def with_id(schema):
    return create_model(schema.__name__ + 'WithID', __base__=schema, resource_id=(UUID, ...))

add('get_profile','profile','GET','/profile',Empty,UserRead,'Read authenticated profile.')
add('update_profile','profile','PATCH','/profile',UserUpdate,UserRead,'Update only supplied profile fields.',True)
class PersonalInfo(InputSchema):
    personal_info: dict[str, Any]
# Root object merge is unwrapped by the client; identity fields are never accepted.
add('merge_personal_info','profile','PATCH','/profile/personal-info',PersonalInfo,UserRead,'Merge top-level personal_info groups; nested groups replace as a whole.',True)
add('onboard','profile','POST','/profile/onboarding',OnboardingInput,UserRead,'Save confirmed onboarding profile, optional metric and goal atomically.',True)
for domain,path,create,read,query,replace in [
    ('metrics','body-metrics',BodyMetricCreate,BodyMetricRead,BodyMetricQuery,BodyMetricCreate),
    ('goals','goals',GoalCreate,GoalRead,Pagination,GoalUpdateRequest),
    ('meals','meals',MealCreate,MealRead,JournalQuery,MealReplace),
    ('trainings','trainings',TrainingCreate,TrainingRead,JournalQuery,TrainingReplace),
    ('foods','foods',FoodCreate,FoodRead,FoodQuery,None),
    ('exercises','exercises',ExerciseCreate,ExerciseRead,ExerciseQuery,None),
]:
    add('list_'+domain,domain,'GET','/'+path,query,list[read],'Search/list '+domain+' with filters and pagination. Empty list means no match.')
    add('get_'+domain,domain,'GET','/'+path+'/{resource_id}',Resource,read,'Read a specific '+domain+' record.')
    add('create_'+domain,domain,'POST','/'+path+('/confirm' if domain=='goals' else ''),create,read,'Propose creation of '+domain+'. Must await human confirmation.',True)
    if replace:
        add('update_'+domain,domain,'PATCH' if domain=='goals' else 'PUT','/'+path+'/{resource_id}',with_id(replace),read,
            'Replace snapshot (returns NEW ID) or patch goal. Read existing record first; preserve omitted snapshot values explicitly.',True)
        add('delete_'+domain,domain,'DELETE','/'+path+'/{resource_id}',VersionedResource if domain in {'meals','trainings'} else Resource,None,'Soft delete the specified record after confirmation.')
add('latest_metrics','metrics','GET','/body-metrics/latest',Empty,BodyMetricRead,'Read latest measurement; 404 means no measurements.')
add('current_goal','goals','GET','/goals/current',Empty,GoalRead,'Read active goal; 404 means no active goal.')
for action in ['complete','cancel']:
    add(action+'_goal','goals','POST','/goals/{resource_id}/'+action,Resource,GoalRead,action+' the active goal after confirmation.')
add('get_progress','progress','GET','/progress',DateRangeQuery,ProgressRead,'Read daily progress for explicit start_date/end_date and timezone.')
