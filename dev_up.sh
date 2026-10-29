#!/usr/bin/env bash
# =============================================================================
# HercFit - Development Environment Launcher (dev_up.sh)
# Khởi chạy toàn bộ hệ thống HercFit: Database (PostgreSQL), Backend API,
# Streamlit UI (tuỳ chọn) và Frontend Web App.
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
FRONTEND_DIR="${ROOT_DIR}/frontend"
COMPOSE_FILE="${BACKEND_DIR}/docker-compose.yml"
FRONTEND_PID_FILE="${ROOT_DIR}/pids/frontend.pid"
FRONTEND_LOG="${ROOT_DIR}/frontend.log"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
VITE_ENTRY="${FRONTEND_DIR}/node_modules/vite/bin/vite.js"

# Colors for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[OK]${NC}   $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERR]${NC}  $*" >&2; }

# Detect docker compose command (v2 plugin vs standalone v1)
get_compose_cmd() {
    if docker compose version >/dev/null 2>&1; then
        echo "docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then
        echo "docker-compose"
    else
        log_error "Docker Compose chưa được cài đặt. Vui lòng cài đặt Docker Desktop."
        exit 1
    fi
}

ensure_env_file() {
    if [[ ! -f "${BACKEND_DIR}/.env" ]]; then
        if [[ -f "${BACKEND_DIR}/.env.example" ]]; then
            cp "${BACKEND_DIR}/.env.example" "${BACKEND_DIR}/.env"
            log_info "Đã khởi tạo ${BACKEND_DIR}/.env từ .env.example"
        else
            log_warn "Không tìm thấy ${BACKEND_DIR}/.env.example"
        fi
    fi
}

print_usage() {
    echo -e "${BOLD}HercFit System Runner (dev_up.sh)${NC}

${BOLD}Cách dùng:${NC}
  ./dev_up.sh [command] [options]

${BOLD}Commands:${NC}
  up          Khởi chạy toàn bộ hệ thống (Mặc định)
  down        Dừng toàn bộ hệ thống và containers
  restart     Khởi động lại toàn bộ hệ thống
  logs        Xem logs trực tiếp từ hạ tầng Docker
  status      Kiểm tra trạng thái các dịch vụ

${BOLD}Options:${NC}
  -d, --detach      Chạy ngầm (detached mode)
  --db-only         Chỉ khởi chạy PostgreSQL database trong Docker
  --frontend-only   Chỉ chạy landing page, không cần Docker hoặc Backend
  --local           Chạy PostgreSQL trên Docker, còn Backend & Frontend chạy trực tiếp trên máy host
  --kg              Khởi chạy thêm Neo4j và worker Knowledge Graph (KG_MODE mặc định off)
  --memory          Khởi chạy thêm Redis cho session memory của agent (SESSION_MEMORY_MODE mặc định off)
  --no-build        Không build lại Docker image khi khởi chạy
  -h, --help        Hiển thị hướng dẫn này

${BOLD}Chạy nhanh landing page:${NC}
  ./dev_up.sh --frontend-only
  ./dev_up.sh --frontend-only -d
  ./dev_up.sh down --frontend-only
  FRONTEND_PORT=5174 ./dev_up.sh --frontend-only"
}

# Parse arguments
COMMAND="up"
DETACH=false
WITH_UI=false
WITH_KG=false
WITH_MEMORY=false
DB_ONLY=false
FRONTEND_ONLY=false
LOCAL_MODE=false
BUILD_FLAG="--build"

while [[ $# -gt 0 ]]; do
    case "$1" in
        up|down|stop|restart|logs|status)
            COMMAND="$1"
            shift
            ;;
        -d|--detach)
            DETACH=true
            shift
            ;;
        --ui|--streamlit|--full)
            log_warn "Streamlit UI đã được gỡ bỏ (không còn streamlit_app.py); bỏ qua ${1}."
            shift
            ;;
        --db-only)
            DB_ONLY=true
            shift
            ;;
        --kg)
            WITH_KG=true
            shift
            ;;
        --memory)
            WITH_MEMORY=true
            shift
            ;;
        --frontend-only)
            FRONTEND_ONLY=true
            shift
            ;;
        --local)
            LOCAL_MODE=true
            shift
            ;;
        --no-build)
            BUILD_FLAG=""
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            log_error "Tham số không hợp lệ: $1"
            print_usage
            exit 1
            ;;
    esac
done

if [[ "${FRONTEND_ONLY}" == true ]] && { [[ "${DB_ONLY}" == true ]] || [[ "${LOCAL_MODE}" == true ]] || [[ "${WITH_UI}" == true ]] || [[ "${WITH_KG}" == true ]] || [[ "${WITH_MEMORY}" == true ]]; }; then
    log_error "--frontend-only không kết hợp với --db-only, --local, --ui, --kg hoặc --memory."
    exit 1
fi

COMPOSE_CMD=""
if [[ "${FRONTEND_ONLY}" == false ]]; then
    COMPOSE_CMD="$(get_compose_cmd)"
fi
FRONTEND_PID=""
BACKEND_PID=""
KG_WORKER_PID=""

frontend_is_running() {
    [[ -f "${FRONTEND_PID_FILE}" ]] || return 1
    local pid command_line
    pid="$(cat "${FRONTEND_PID_FILE}")"
    [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
    kill -0 "${pid}" 2>/dev/null || return 1
    command_line="$(ps -p "${pid}" -o args= 2>/dev/null)" || return 1
    [[ "${command_line}" == *"${VITE_ENTRY}"* ]]
}

stop_frontend() {
    if frontend_is_running; then
        log_info "Đang dừng Frontend dev server..."
        kill "$(cat "${FRONTEND_PID_FILE}")" 2>/dev/null || true
    fi
    rm -f "${FRONTEND_PID_FILE}"
}

cleanup() {
    local exit_code=$?
    if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
        log_info "Đang dừng Frontend dev server (PID ${FRONTEND_PID})..."
        kill "${FRONTEND_PID}" 2>/dev/null || true
        rm -f "${FRONTEND_PID_FILE}"
    fi
    if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
        log_info "Đang dừng Local Backend server (PID ${BACKEND_PID})..."
        kill "${BACKEND_PID}" 2>/dev/null || true
    fi
    exit "${exit_code}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

start_frontend_if_available() {
    if [[ -f "${FRONTEND_DIR}/package.json" ]]; then
        if frontend_is_running; then
            log_success "Frontend đã chạy (PID: $(cat "${FRONTEND_PID_FILE}"))."
            return
        fi
        if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
            log_error "Cần Node.js và npm để chạy landing page."
            return 1
        fi
        log_info "Phát hiện mã nguồn Frontend tại ${FRONTEND_DIR}. Đang chuẩn bị khởi chạy..."
        (
            cd "${FRONTEND_DIR}"
            if [[ ! -f "${VITE_ENTRY}" ]]; then
                log_info "Đang cài đặt dependencies cho Frontend..."
                npm ci
            fi
        )
        mkdir -p "$(dirname "${FRONTEND_PID_FILE}")"
        # exec giữ đúng PID của Vite để Ctrl+C và down dừng đúng server.
        (
            cd "${FRONTEND_DIR}"
            exec nohup node "${VITE_ENTRY}" --host 127.0.0.1 --port "${FRONTEND_PORT}" --strictPort
        ) > "${FRONTEND_LOG}" 2>&1 < /dev/null &
        FRONTEND_PID=$!
        echo "${FRONTEND_PID}" > "${FRONTEND_PID_FILE}"
        local attempt
        for ((attempt=1; attempt<=30; attempt++)); do
            if ! kill -0 "${FRONTEND_PID}" 2>/dev/null; then
                log_error "Không khởi chạy được Frontend. Xem ${FRONTEND_LOG}."
                return 1
            fi
            if curl -fsS --max-time 1 "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
                # Không báo thành công nếu cổng đang thuộc một server khác.
                sleep 1
                kill -0 "${FRONTEND_PID}" 2>/dev/null || {
                    log_error "Frontend đã thoát. Kiểm tra cổng ${FRONTEND_PORT} và ${FRONTEND_LOG}."
                    return 1
                }
                log_success "Landing page: http://localhost:${FRONTEND_PORT} (logs: ${FRONTEND_LOG})"
                if [[ "${DETACH}" == true ]]; then
                    FRONTEND_PID=""
                fi
                return
            fi
            sleep 1
        done
        log_error "Frontend chưa sẵn sàng. Xem ${FRONTEND_LOG}."
        return 1
    else
        log_warn "Thư mục /frontend chưa có package.json — bỏ qua bước khởi chạy Frontend."
    fi
}

wait_for_backend_health() {
    local url="http://localhost:${PORT:-8080}/health"
    local retries=30
    log_info "Đang chờ Backend API sẵn sàng tại ${url} ..."
    for ((i=1; i<=retries; i++)); do
        if curl -fsS "${url}" >/dev/null 2>&1; then
            log_success "Backend API đã sẵn sàng!"
            return 0
        fi
        sleep 2
    done
    log_warn "Backend API chưa phản hồi sau $((retries * 2))s. Kiểm tra logs bằng: ./dev_up.sh logs"
}

print_summary() {
    echo ""
    echo -e "${CYAN}=================================================================${NC}"
    echo -e "${BOLD}${GREEN}🚀 Hệ thống HercFit đã được khởi chạy!${NC}"
    echo -e "${CYAN}=================================================================${NC}"
    echo -e "  • ${BOLD}PostgreSQL DB:${NC}    localhost:${POSTGRES_PORT:-5432} (db: ${POSTGRES_DB:-hercfit_db}, user: ${POSTGRES_USER:-hercfit})"
    if [[ "${DB_ONLY}" == false ]]; then
        echo -e "  • ${BOLD}Backend API:${NC}      http://localhost:${PORT:-8080}"
        echo -e "  • ${BOLD}Swagger API Docs:${NC} http://localhost:${PORT:-8080}/docs"
        echo -e "  • ${BOLD}Health Check:${NC}     http://localhost:${PORT:-8080}/health"
    fi
    if [[ "${WITH_UI}" == true ]]; then
        echo -e "  • ${BOLD}Streamlit UI:${NC}     http://localhost:${STREAMLIT_PORT:-8501}"
    fi
    if [[ "${WITH_KG}" == true ]]; then
        echo -e "  • ${BOLD}Neo4j Browser:${NC}    http://localhost:${NEO4J_HTTP_PORT:-7474} (KG_MODE=${KG_MODE:-off})"
    fi
    if [[ "${WITH_MEMORY}" == true ]]; then
        echo -e "  • ${BOLD}Redis memory:${NC}     localhost:${REDIS_PORT:-6379} (SESSION_MEMORY_MODE=${SESSION_MEMORY_MODE:-off})"
    fi
    if [[ "${DB_ONLY}" == false ]] && [[ -f "${FRONTEND_DIR}/package.json" ]]; then
        echo -e "  • ${BOLD}Frontend App:${NC}     http://localhost:${FRONTEND_PORT}"
    fi
    echo -e "${CYAN}=================================================================${NC}"
    echo -e "  Lệnh hữu ích: ${YELLOW}./dev_up.sh logs${NC} | ${YELLOW}./dev_up.sh status${NC} | ${YELLOW}./dev_up.sh down${NC}"
    echo ""
}

if [[ "${FRONTEND_ONLY}" == true ]]; then
    case "${COMMAND}" in
        down|stop) stop_frontend ;;
        status)
            if frontend_is_running; then
                log_success "Frontend đang chạy (PID: $(cat "${FRONTEND_PID_FILE}"))."
            else
                log_info "Frontend chưa chạy."
            fi
            ;;
        logs)
            [[ -f "${FRONTEND_LOG}" ]] || { log_error "Chưa có log Frontend."; exit 1; }
            tail -n 50 -f "${FRONTEND_LOG}"
            ;;
        up|restart)
            if [[ "${COMMAND}" == restart ]]; then
                stop_frontend
                sleep 1
            fi
            start_frontend_if_available
            if [[ -n "${FRONTEND_PID}" ]]; then
                log_info "Nhấn Ctrl+C để dừng landing page."
                wait "${FRONTEND_PID}"
            fi
            ;;
    esac
    exit 0
fi

case "${COMMAND}" in
    down|stop)
        log_info "Đang dừng toàn bộ dịch vụ HercFit..."
        stop_frontend
        ${COMPOSE_CMD} -f "${COMPOSE_FILE}" --profile full --profile kg --profile memory down
        log_success "Đã dừng toàn bộ hệ thống."
        ;;

    restart)
        log_info "Đang khởi động lại hệ thống HercFit..."
        stop_frontend
        ${COMPOSE_CMD} -f "${COMPOSE_FILE}" --profile full --profile kg --profile memory down
        RESTART_ARGS=(up)
        [[ "${WITH_KG}" == true ]] && RESTART_ARGS+=(--kg)
        [[ "${WITH_MEMORY}" == true ]] && RESTART_ARGS+=(--memory)
        [[ "${LOCAL_MODE}" == true ]] && RESTART_ARGS+=(--local)
        [[ "${WITH_UI}" == true ]] && RESTART_ARGS+=(--ui)
        [[ "${DETACH}" == true ]] && RESTART_ARGS+=(--detach)
        exec "$0" "${RESTART_ARGS[@]}"
        ;;

    logs)
        ${COMPOSE_CMD} -f "${COMPOSE_FILE}" --profile full --profile kg --profile memory logs -f
        ;;

    status)
        if frontend_is_running; then
            log_success "Frontend đang chạy (PID: $(cat "${FRONTEND_PID_FILE}"))."
        else
            log_info "Frontend chưa chạy."
        fi
        ${COMPOSE_CMD} -f "${COMPOSE_FILE}" --profile full --profile kg --profile memory ps
        ;;

    up)
        ensure_env_file
        # Load environment variables from backend/.env if present
        set -a
        # shellcheck disable=SC1091
        [[ -f "${BACKEND_DIR}/.env" ]] && source "${BACKEND_DIR}/.env"
        set +a

        if [[ "${DB_ONLY}" == true ]]; then
            log_info "Đang khởi tạo PostgreSQL Database qua Docker..."
            ${COMPOSE_CMD} -f "${COMPOSE_FILE}" up -d postgres
            if [[ "${WITH_KG}" == true ]]; then
                ${COMPOSE_CMD} -f "${COMPOSE_FILE}" --profile kg up -d neo4j
            fi
            if [[ "${WITH_MEMORY}" == true ]]; then
                ${COMPOSE_CMD} -f "${COMPOSE_FILE}" --profile memory up -d redis
            fi
            print_summary
            exit 0
        fi

        if [[ "${LOCAL_MODE}" == true ]]; then
            log_info "Chế độ LOCAL: Khởi chạy PostgreSQL trong Docker + Backend/Frontend trực tiếp trên máy..."
            ${COMPOSE_CMD} -f "${COMPOSE_FILE}" up -d postgres
            if [[ "${WITH_MEMORY}" == true ]]; then
                ${COMPOSE_CMD} -f "${COMPOSE_FILE}" --profile memory up -d redis
            fi

            if [[ "${WITH_KG}" == true ]]; then
                ${COMPOSE_CMD} -f "${COMPOSE_FILE}" --profile kg up -d neo4j
                log_info "Chuẩn bị migrations và worker KG bằng Python môi trường dự án..."
                KG_PYTHON="${ROOT_DIR}/.venv/bin/python"
                [[ -x "${KG_PYTHON}" ]] || KG_PYTHON="$(command -v python3)"
                (
                    cd "${BACKEND_DIR}"
                    export POSTGRES_HOST=localhost
                    "${KG_PYTHON}" -m alembic upgrade head
                    "${KG_PYTHON}" -m agentic.scripts.migrate
                )
                (
                    cd "${BACKEND_DIR}"
                    export NEO4J_URI="bolt://localhost:${NEO4J_BOLT_PORT:-7687}"
                    export NEO4J_PASSWORD="${NEO4J_PASSWORD:-hercfit-graph-dev}"
                    exec "${KG_PYTHON}" -m agentic.knowledge_graph.worker run
                ) &
                KG_WORKER_PID=$!
                trap '[[ -z "${KG_WORKER_PID}" ]] || kill "${KG_WORKER_PID}" 2>/dev/null || true' EXIT
            fi

            log_info "Đang khởi chạy Backend FastAPI server tại ${BACKEND_DIR}..."
            (
                cd "${BACKEND_DIR}"
                export POSTGRES_HOST=localhost
                python3 run_service.py
            ) &
            BACKEND_PID=$!

            wait_for_backend_health
            start_frontend_if_available
            print_summary

            wait
            exit 0
        fi

        # Standard Docker mode for Backend + Database
        PROFILE_ARGS=()
        if [[ "${WITH_UI}" == true ]]; then
            PROFILE_ARGS+=(--profile ui)
        fi
        if [[ "${WITH_KG}" == true ]]; then
            PROFILE_ARGS+=(--profile kg)
        fi
        if [[ "${WITH_MEMORY}" == true ]]; then
            PROFILE_ARGS+=(--profile memory)
        fi

        log_info "Đang khởi chạy hạ tầng Backend & Database qua Docker Compose..."
        # shellcheck disable=SC2086
        ${COMPOSE_CMD} -f "${COMPOSE_FILE}" "${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"}" up -d ${BUILD_FLAG}

        wait_for_backend_health
        start_frontend_if_available
        print_summary

        if [[ "${DETACH}" == false ]]; then
            log_info "Đang theo dõi logs hệ thống (Nhấn Ctrl+C để thoát chế độ xem logs, containers vẫn chạy)..."
            ${COMPOSE_CMD} -f "${COMPOSE_FILE}" "${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"}" logs -f
        fi
        ;;
esac
