"""Runtime installation for Phase 11's conservative feature ports."""
from __future__ import annotations

from .feature_porting import apply_enum_coercion_in_place


def install_phase11_feature_porting() -> None:
    """Integrate safe enum coercion into the existing validation boundary.

    The existing Phase 4 runtime owns validation/repair. We wrap that boundary
    instead of duplicating it, so enum normalization is applied consistently to
    both first-pass and repaired tool calls without executing downstream tools.
    """
    from . import phase4_runtime

    if getattr(phase4_runtime, "_phase11_feature_porting_installed", False):
        return

    original_validate = phase4_runtime.validate_tool_calls

    def validate_with_feature_porting(tool_calls, tool_defs=None):
        apply_enum_coercion_in_place(tool_calls, tool_defs)
        return original_validate(tool_calls, tool_defs)

    phase4_runtime.validate_tool_calls = validate_with_feature_porting
    phase4_runtime._phase11_feature_porting_installed = True
