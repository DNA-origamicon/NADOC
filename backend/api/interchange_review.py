"""Require an up-to-date loss review before an interchange download."""

from fastapi import HTTPException
from backend.core.interchange_compatibility import compatibility_report


def require_review(design, target, token):
    report = compatibility_report(design, target)
    if report["blocked"]:
        raise HTTPException(
            422,
            detail={
                "message": "Export blocked: unsupported molecular content or invalid topology.",
                "compatibility": report,
            },
        )
    if report["issues"] and token != report["token"]:
        raise HTTPException(
            409,
            detail={
                "message": "Review the current design compatibility report before exporting.",
                "compatibility": report,
            },
        )
