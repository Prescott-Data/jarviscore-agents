"""Launch with python -m server; credentials only from the shell/explicit env file."""

import argparse
import os
from pathlib import Path


def parser():
    result = argparse.ArgumentParser(description="Local-only JarvisCore agent desk")
    result.add_argument("--host", choices=("127.0.0.1", "localhost", "::1"), default="127.0.0.1")
    result.add_argument("--port", type=int, default=8765)
    result.add_argument("--env-file", type=Path, help="Explicit local credentials file; never sent to UI")
    result.add_argument("--config", type=Path, help="Trusted local desk YAML; imports your installed mesh factory")
    result.add_argument(
        "--framework-source", type=Path, default=os.environ.get("JARVISCORE_FRAMEWORK_SOURCE"),
        help="Require this editable framework checkout; refuse a wheel or another source tree",
    )
    result.add_argument("--load-entry-points", action="store_true", help="Load trusted installed adapters")
    return result


def main():
    args = parser().parse_args()
    if not 1 <= args.port <= 65535:
        parser().error("port must be between 1 and 65535")
    os.umask(0o077)
    if args.env_file:
        from dotenv import dotenv_values

        if not args.env_file.is_file():
            parser().error("explicit environment file does not exist")
        for key, value in dotenv_values(args.env_file, interpolate=False).items():
            if value is not None:
                os.environ.setdefault(key, value)
    # Agent packages and the framework must not discover a different .env implicitly.
    os.environ["PYTHON_DOTENV_DISABLED"] = "1"
    if args.framework_source:
        from .framework import require_framework_source

        try:
            require_framework_source(args.framework_source)
        except (ValueError, OSError, KeyError) as exc:
            parser().error(str(exc))
        os.environ["JARVISCORE_FRAMEWORK_SOURCE"] = str(args.framework_source.expanduser().resolve())
    import uvicorn

    from .app import create_app

    config, registry = None, None
    if args.config:
        from .config import configured_registry

        config, registry = configured_registry(args.config)
    uvicorn.run(
        create_app(load_entry_points=args.load_entry_points, config=config, registry=registry,
                   room_config=args.config if config is not None and config.room_factory else None),
        host=args.host, port=args.port,
        proxy_headers=False, access_log=False, workers=1, timeout_graceful_shutdown=3,
    )


if __name__ == "__main__":
    main()
