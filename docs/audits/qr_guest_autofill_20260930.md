# Android QR guest entry and saved-password suggestions

The reported “Use saved password?” popup is browser/password-manager UI, not
NADOC UI. The Android browser/provider has not yet been identified, so the exact
trigger on that device is unconfirmed. It does not by itself imply bad settings.

## Research

- [Chromium security FAQ](https://github.com/chromium/chromium/blob/main/docs/security/faq.md#why-does-the-password-manager-ignore-autocompleteoff-for-password-fields):
  Chromium intentionally ignores autocomplete=off for password management,
  prioritizing the user's password-manager choice over a website's preference.
- [MDN's autocomplete guidance](https://developer.mozilla.org/en-US/docs/Web/Security/Practical_implementation_guides/Turning_off_form_autocompletion):
  disabling autocomplete is not a universal way to suppress login suggestions.
- [Chromium's form parser](https://raw.githubusercontent.com/chromium/chromium/main/components/password_manager/core/browser/form_parsing/form_data_parser.cc):
  password-field detection and username heuristics are separate from normal
  autocomplete. FindUsernameFieldBaseHeuristics considers text fields preceding
  password fields. It also supports single-username forms, so eliminating a
  password field is not a universal password-manager prohibition.

The old viewer HTML always contained a type=password input immediately after
Display name. JavaScript disabled it and hid its row for QR entry. That was a
plausible credential-classification trigger even though guests could not see it.
This is an inference from our markup and the browser design, not proof from the
user's Android password-manager internals.

## Implemented mitigation

Remove all password inputs from initial viewer HTML. QR/passwordless entry never
mounts one. The meeting_password module creates a labeled, masked, required input
only for an invitation that requires a password, then clears/removes it on disposal.
The existing name field, accessibility, mobile keyboard, Unicode typing, native
validation, and manager opt-out hints remain intact. No fake password fields,
readonly-focus tricks, custom keyboard, or misleading new-password hint is used.
No guest settings changes are required to try this mitigation.

Verification distinguishes the DOM change from the Android outcome: unit tests
cover password-required entry and disposal/reuse; production browser tests watch
DOM mutations from document start and assert that no password input is ever added
during QR entry. Desktop Chromium with mobile emulation does not reproduce native
Android Password Manager or Samsung Pass UI. A fresh QR page on the affected phone
is still needed to establish whether its popup disappears.

main.js LOC delta: 0. Evidence: .development-artifacts/qr-autofill-20260930/.

Validation: 581 frontend test files / 7,310 tests passed (one skipped). Six
production-host browser checks, one mobile touch/password-flow check, and one
HTTPS protected-entry check passed. The HTTPS fixture needed its scene bundled
with CSS ignored for Node, matching the prepared-host fixture; its stale shutdown
assertion was updated to the current explicit Session ended screen. Initial
failures and successful reruns are retained in the evidence directory.
Final smoke: 23 passed. Build, lint and diff checks passed. Post-run scans found
no test workspace entries, temporary host/TLS fixtures, or browser output directories.
