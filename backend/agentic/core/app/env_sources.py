"""Giải quyết bí danh URL gateway mà không đổi thứ tự ưu tiên của các nguồn settings."""

from pydantic_settings import DotEnvSettingsSource


def canonical_jev_url(values, *, case_sensitive=True):
    values = dict(values)
    base, gateway = ("JEV_BASE_URL", "JEV_GATEWAY_URL")
    if not case_sensitive:
        base, gateway = base.lower(), gateway.lower()
    if gateway in values:
        values.setdefault(base, values.pop(gateway))
    return values


class JevDotEnvSettingsSource(DotEnvSettingsSource):
    def _read_env_file(self, file_path):
        # Chuẩn hoá từng file trước khi gộp: .env của agent phải ghi đè .env dùng chung
        # kể cả khi hai bên đặt tên khác nhau cho cùng một thiết lập.
        return canonical_jev_url(
            super()._read_env_file(file_path), case_sensitive=self.case_sensitive
        )


def canonical_source(source):
    def read():
        return canonical_jev_url(source())

    return read
