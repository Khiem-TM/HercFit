import axios from 'axios'

/**
 * Base Axios instance kết nối tới FastAPI Backend.
 * TODO: Bổ sung interceptors cho JWT Auth và xử lý lỗi tập trung.
 */
export const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000,
  headers: {
    'Content-Type': 'application/json',
  },
})

export const usersApi = {
  // TODO: GET /users/profile, PATCH /users/profile, GET/POST /users/metrics
}

export const nutritionApi = {
  // TODO: GET /nutrition/summary, POST /nutrition/meals
}

export const workoutsApi = {
  // TODO: GET/POST /workouts/plans, GET/POST /workouts/sessions
}

export const agentApi = {
  // TODO: POST /invoke, POST /stream, GET /info, POST /history
}
