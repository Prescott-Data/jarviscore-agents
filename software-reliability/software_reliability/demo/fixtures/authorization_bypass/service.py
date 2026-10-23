"""Minimal service configuration with an authorization defect."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Handler:
    path: str = ""


@dataclass(frozen=True)
class Service:
    handlers: tuple[Handler, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ServeConfig:
    web_handlers: tuple[Handler, ...] = field(default_factory=tuple)
    services: tuple[Service, ...] = field(default_factory=tuple)


def has_path_handler(config: ServeConfig) -> bool:
    return any(handler.path for handler in config.web_handlers)


def authorize(config: ServeConfig, *, is_admin: bool) -> bool:
    if not has_path_handler(config):
        return True
    return is_admin
