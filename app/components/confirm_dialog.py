"""Two-step confirmation for irreversible actions (submit-for-review, in
particular — D14 makes submission permanent: the request always stays
visible to the admin). Deliberately not a modal — st.dialog reruns the whole
script on open/close in ways that are awkward to reason about alongside a
page's other session state, so this uses a plain checkbox-then-button gate
instead. See docs/UI_SPEC.md #2.
"""

from __future__ import annotations

import streamlit as st


def confirm_action(*, message: str, confirm_label: str, key_prefix: str) -> bool:
    """Returns True exactly once, on the render where the user both checked
    the acknowledgement box and clicked the confirm button.
    """
    st.warning(message, icon="⚠️")
    acknowledged = st.checkbox("I understand and want to proceed", key=f"{key_prefix}_ack")
    return acknowledged and st.button(
        confirm_label, key=f"{key_prefix}_confirm", type="primary", disabled=not acknowledged
    )
