from copy import deepcopy
from html import escape

from fastapi import FastAPI, Request
from fastapi.openapi.docs import get_redoc_html
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from backend.presentation.api.documentation.openapi import Locale, LocalizedOpenAPI


def register_documentation(app: FastAPI) -> None:
    documentation = LocalizedOpenAPI(app)
    app.openapi = lambda: documentation.schema("en")

    @app.get("/openapi/{locale}.json", include_in_schema=False)
    def localized_openapi(request: Request, locale: Locale) -> JSONResponse:
        schema = documentation.schema(locale)
        root_path = request.scope.get("root_path", "").rstrip("/")
        if root_path and app.root_path_in_servers:
            schema = deepcopy(schema)
            schema["servers"] = [{"url": root_path}] + [
                server for server in schema.get("servers", []) if server["url"] != root_path
            ]
        return JSONResponse(schema, headers={"Content-Language": locale})

    @app.get("/redoc", include_in_schema=False)
    def default_redoc(request: Request) -> RedirectResponse:
        root_path = request.scope.get("root_path", "").rstrip("/")
        return RedirectResponse(f"{root_path}/redoc/ru")

    @app.get("/redoc/{locale}", include_in_schema=False)
    def localized_redoc(request: Request, locale: Locale) -> HTMLResponse:
        root_path = escape(request.scope.get("root_path", "").rstrip("/"), quote=True)
        page = get_redoc_html(
            openapi_url=f"{root_path}/openapi/{locale}.json",
            title=f"{escape(app.title)} — {locale.upper()}",
            with_google_fonts=False,
        ).body.decode("utf-8")
        label = "Язык документации" if locale == "ru" else "Documentation language"
        links = " ".join(
            f'<a href="{root_path}/redoc/{language}" lang="{language}" '
            f'hreflang="{language}"'
            + (' aria-current="page"' if language == locale else '')
            + f'>{language.upper()}</a>'
            for language in ("ru", "en")
        )
        navigation = (
            f'<nav class="docs-nav" aria-label="{label}">'
            f'<strong>{escape(app.title)}</strong><span>{label}: {links}</span>'
            f'<a href="{root_path}/openapi/{locale}.json">OpenAPI JSON</a></nav>'
        )
        styles = """<style>
            .docs-nav {display:flex;align-items:center;gap:24px;flex-wrap:wrap;
                padding:16px 24px;border-bottom:1px solid #dbe3eb;
                font-family:system-ui,sans-serif;color:#172b4d;background:#f7f9fc}
            .docs-nav strong {margin-right:auto}
            .docs-nav a {color:#1458a8;margin-left:8px;text-decoration:none}
            .docs-nav a[aria-current] {font-weight:700;text-decoration:underline}
            .docs-nav a:focus-visible {outline:2px solid #1458a8;outline-offset:4px}
        </style>"""
        page = page.replace("<html>", f'<html lang="{locale}">')
        page = page.replace("</head>", styles + "</head>")
        page = page.replace("<body>", "<body>" + navigation)
        if locale == "ru":
            page = page.replace(
                "ReDoc requires Javascript to function. Please enable it to browse the documentation.",
                "Для просмотра документации ReDoc включите JavaScript в браузере.",
            )
        return HTMLResponse(page, headers={"Content-Language": locale})
