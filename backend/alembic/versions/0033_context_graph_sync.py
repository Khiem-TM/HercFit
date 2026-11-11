"""Đồng bộ chặt cho Context Graph: pg_notify khi ghi outbox, index sự kiện chưa giao theo chủ sở hữu, lịch sử mục tiêu.

* Trigger cấp câu lệnh trên kg_outbox gọi pg_notify('kg_outbox'); worker LISTEN nên chiếu ngay khi transaction nguồn
  commit thay vì chờ chu kỳ poll (cả sự kiện của backend lẫn của agent).
* Index riêng phần kg_outbox(owner_id) WHERE delivered_at IS NULL cho cổng read-your-writes của agent.
* Mục tiêu đã kết thúc không còn bị chiếu thành tombstone: graph giữ chúng cùng trạng thái. Các mục tiêu đó được phát
  lại một lần ở đây.

Downgrade chỉ bỏ index: thân hàm do code hiện tại sinh ra (thông báo thừa và mục tiêu đã kết thúc vô hại với worker cũ).
"""
from alembic import op

from core.graph_outbox import installation_statements

revision = "0033_context_graph_sync"
down_revision = "0032_food_mass_basis"
branch_labels = None
depends_on = None


def upgrade():
    for statement in installation_statements():
        op.execute(statement)
    op.execute(
        "SELECT kg_publish_backend('Goal', to_jsonb(g)) FROM goals g "
        "WHERE g.is_active AND g.status::text <> 'IN_PROGRESS'"
    )


def downgrade():
    op.execute("DROP TRIGGER IF EXISTS kg_outbox_notify ON kg_outbox")
    op.execute("DROP FUNCTION IF EXISTS kg_outbox_notify()")
    op.execute("DROP INDEX IF EXISTS ix_kg_outbox_owner_pending")
