#!/usr/bin/env bash
# =============================================================================
# HercFit - Development Environment Launcher (dev_up.sh)
# Khởi chạy toàn bộ hệ thống HercFit: Database (PostgreSQL), Backend API,
# Agentic Service (Multi-Agent AI), Streamlit UI (tuỳ chọn) và Frontend Web App.
# =============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="${ROOT_DIR}/backend"
AGENTIC_DIR="${BACKEND_DIR}/agentic"
FRONTEND_DIR="${ROOT_DIR}/frontend"
COMPOSE_FILE="${BACKEND_DIR}/docker-compose.yml"

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

    if [[ ! -f "${AGENTIC_DIR}/.env" ]]; then
        if [[ -f "${AGENTIC_DIR}/.env.example" ]]; then
            cp "${AGENTIC_DIR}/.env.example" "${AGENTIC_DIR}/.env"
            log_info "Đã khởi tạo ${AGENTIC_DIR}/.env từ .env.example"
        else
            log_warn "Không tìm thấy ${AGENTIC_DIR}/.env.example"
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

${BOLD}Options (cho lệnh 'up'):${NC}
  -d, --detach      Chạy ngầm (detached mode)
  --ui, --streamlit Khởi chạy kèm giao diện Streamlit UI (port 8501)
  --no-agent        Không khởi chạy Agentic Service (chỉ chạy CRUD Backend + DB)
  --db-only         Chỉ khởi chạy PostgreSQL database trong Docker
  --local           Chạy PostgreSQL trên Docker, còn Backend, Agentic & Frontend chạy trực tiếp trên máy host
  --no-build        Không build lại Docker image khi khởi chạy
  -h, --help        Hiển thị hướng dẫn này"
}

# Parse arguments
COMMAND="up"
DETACH=false
WITH_UI=false
WITH_AGENT=true
DB_ONLY=false
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
            WITH_UI=true
            shift
            ;;
        --no-agent)
            WITH_AGENT=false
            shift
            ;;
        --db-only)
            DB_ONLY=true
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

COMPOSE_CMD="$(get_compose_cmd)"
FRONTEND_PID=""
BACKEND_PID=""
AGENTIC_PID=""

cleanup() {
    local exit_code=$?
    if [[ -n "${FRONTEND_PID}" ]] && kill -0 "${FRONTEND_PID}" 2>/dev/null; then
        log_info "Đang dừng Frontend dev server (PID ${FRONTEND_PID})..."
        kill "${FRONTEND_PID}" 2>/dev/null || true
    fi
    if [[ -n "${AGENTIC_PID}" ]] && kill -0 "${AGENTIC_PID}" 2>/dev/null; then
        log_info "Đang dừng Local Agentic server (PID ${AGENTIC_PID})..."
        kill "${AGENTIC_PID}" 2>/dev/null || true
    fi
    if [[ -n "${BACKEND_PID}" ]] && kill -0 "${BACKEND_PID}" 2>/dev/null; then
        log_info "Đang dừng Local Backend server (PID ${BACKEND_PID})..."
        kill "${BACKEND_PID}" 2>/dev/null || true
    fi
    exit "${exit_code}"
}
trap cleanup INT TERM

start_frontend_if_available() {
    if [[ -f "${FRONTEND_DIR}/package.json" ]]; then
        log_info "Phát hiện mã nguồn Frontend tại ${FRONTEND_DIR}. Đang chuẩn bị khởi chạy..."
        (
            cd "${FRONTEND_DIR}"
            if [[ ! -d "node_modules" ]]; then
                log_info "Đang cài đặt dependencies cho Frontend..."
                if command -v pnpm >/dev/null 2>&1 && [[ -f "pnpm-lock.yaml" ]]; then
                    pnpm install
                elif command -v yarn >/dev/null 2>&1 && [[ -f "yarn.lock" ]]; then
                    yarn install
                else
                    npm install
                fi
            fi

            if [[ "${DETACH}" == true ]]; then
                nohup npm run dev > "${ROOT_DIR}/frontend.log" 2>&1 &
                log_success "Frontend đang chạy ngầm (logs: ${ROOT_DIR}/frontend.log)"
            else
                npm run dev &
                FRONTEND_PID=$!
                log_success "Frontend dev server đã khởi chạy (PID: ${FRONTEND_PID})"
            fi
        )
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

wait_for_agentic_health() {
    if [[ "${WITH_AGENT}" == false ]]; then
        return 0
    fi
    local url="http://localhost:${AGENT_PORT:-8081}/health"
    local retries=30
    log_info "Đang chờ Agentic Service sẵn sàng tại ${url} ..."
    for ((i=1; i<=retries; i++)); do
        if curl -fsS "${url}" >/dev/null 2>&1; then
            log_success "Agentic Service đã sẵn sàng!"
            return 0
        fi
        sleep 2
    done
    log_warn "Agentic Service chưa phản hồi sau $((retries * 2))s. Kiểm tra logs bằng: ./dev_up.sh logs"
}

print_summary() {
    echo ""
    echo -e "${CYAN}=================================================================${NC}"
    echo -e "${BOLD}${GREEN}🚀 Hệ thống HercFit đã được khởi chạy!${NC}"
    echo -e "${CYAN}=================================================================${NC}"
    echo -e "  • ${BOLD}PostgreSQL DB:${NC}      localhost:${POSTGRES_PORT:-5432} (db: ${POSTGRES_DB:-hercfit_db}, user: ${POSTGRES_USER:-hercfit})"
    if [[ "${DB_ONLY}" == false ]]; then
        echo -e "  • ${BOLD}Backend API:${NC}        http://localhost:${PORT:-8080}"
        echo -e "  • ${BOLD}Backend Swagger:${NC}    http://localhost:${PORT:-8080}/docs"
        echo -e "  • ${BOLD}Backend Health:${NC}     http://localhost:${PORT:-8080}/health"
        if [[ "${WITH_AGENT}" == true ]]; then
            echo -e "  • ${BOLD}Agentic API:${NC}        http://localhost:${AGENT_PORT:-8081}"
            echo -e "  • ${BOLD}Agentic Swagger:${NC}    http://localhost:${AGENT_PORT:-8081}/docs"
            echo -e "  • ${BOLD}Agentic Health:${NC}     http://localhost:${AGENT_PORT:-8081}/health"
        fi
    fi
    if [[ "${WITH_UI}" == true ]]; then
        echo -e "  • ${BOLD}Streamlit UI:${NC}       http://localhost:${STREAMLIT_PORT:-8501}"
    fi
    if [[ -f "${FRONTEND_DIR}/package.json" ]]; then
        echo -e "  • ${BOLD}Frontend App:${NC}       http://localhost:5173"
    fi
    echo -e "${CYAN}=================================================================${NC}"
    echo -e "  Lệnh hữu ích: ${YELLOW}./dev_up.sh logs${NC} | ${YELLOW}./dev_up.sh status${NC} | ${YELLOW}./dev_up.sh down${NC}"
    echo ""
}

case "${COMMAND}" in
    down|stop)
        log_info "Đang dừng toàn bộ dịch vụ HercFit..."
        ${COMPOSE_CMD} -f "${COMPOSE_FILE}" --profile full down
        log_success "Đã dừng toàn bộ hệ thống."
        ;;

    restart)
        log_info "Đang khởi động lại hệ thống HercFit..."
        ${COMPOSE_CMD} -f "${COMPOSE_FILE}" --profile full down
        exec "$0" up
        ;;

    logs)
        ${COMPOSE_CMD} -f "${COMPOSE_FILE}" --profile full logs -f
        ;;

    status)
        ${COMPOSE_CMD} -f "${COMPOSE_FILE}" --profile full ps
        ;;

    up)
        ensure_env_file
        # Load environment variables from backend/.env and backend/agentic/.env if present
        set -a
        # shellcheck disable=SC1091
        [[ -f "${BACKEND_DIR}/.env" ]] && source "${BACKEND_DIR}/.env"
        # shellcheck disable=SC1091
        [[ -f "${AGENTIC_DIR}/.env" ]] && source "${AGENTIC_DIR}/.env"
        set +a

        if [[ "${DB_ONLY}" == true ]]; then
            log_info "Đang khởi tạo PostgreSQL Database qua Docker..."
            ${COMPOSE_CMD} -f "${COMPOSE_FILE}" up -d postgres
            print_summary
            exit 0
        fi

        if [[ "${LOCAL_MODE}" == true ]]; then
            log_info "Chế độ LOCAL: Khởi chạy PostgreSQL trong Docker + Backend/Agentic/Frontend trực tiếp trên máy..."
            ${COMPOSE_CMD} -f "${COMPOSE_FILE}" up -d postgres

            log_info "Đang khởi chạy Backend FastAPI server tại ${BACKEND_DIR}..."
            (
                cd "${BACKEND_DIR}"
                export POSTGRES_HOST=localhost
                python3 run_service.py
            ) &
            BACKEND_PID=$!

            wait_for_backend_health

            if [[ "${WITH_AGENT}" == true ]]; then
                log_info "Đang khởi chạy Agentic Multi-Agent server tại ${AGENTIC_DIR}..."
                (
                    cd "${AGENTIC_DIR}"
                    export POSTGRES_HOST=localhost
                    export BACKEND_BASE_URL="http://localhost:${PORT:-8080}"
                    python3 main.py
                ) &
                AGENTIC_PID=$!
                wait_for_agentic_health
            fi

            start_frontend_if_available
            print_summary

            wait
            exit 0
        fi

        # Standard Docker mode for Backend + Agentic + Database
        PROFILE_ARGS=()
        if [[ "${WITH_UI}" == true ]]; then
            PROFILE_ARGS=(--profile ui)
        fi

        SERVICES=(postgres backend)
        if [[ "${WITH_AGENT}" == true ]]; then
            SERVICES+=(agentic)
        fi
        if [[ "${WITH_UI}" == true ]]; then
            SERVICES+=(streamlit)
        fi

        log_info "Đang khởi chạy hạ tầng Backend, Agentic & Database qua Docker Compose..."
        # shellcheck disable=SC2086
        ${COMPOSE_CMD} -f "${COMPOSE_FILE}" "${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"}" up -d ${BUILD_FLAG} "${SERVICES[@]}"

        wait_for_backend_health
        wait_for_agentic_health
        start_frontend_if_available
        print_summary

        if [[ "${DETACH}" == false ]]; then
            log_info "Đang theo dõi logs hệ thống (Nhấn Ctrl+C để thoát chế độ xem logs, containers vẫn chạy)..."
            ${COMPOSE_CMD} -f "${COMPOSE_FILE}" "${PROFILE_ARGS[@]+"${PROFILE_ARGS[@]}"}" logs -f "${SERVICES[@]}"
        fi
        ;;
esac
