---
name: Interrupt before doubting what the user reports seeing
description: When about to second-guess a user observation and change code preemptively, ask first instead of acting.
type: feedback
---

When I start doubting what the user says they are seeing (e.g., "the highlights don't change based on direction"), I should stop and ask a clarifying question before making any code changes. Acting on doubt without asking risks changing code that was correct, based on a misread of the situation.

**Why:** User explicitly flagged this: "Add an interrupt to any thinking process where you doubt what I am seeing." In this case the code was correct and the user had simply not noticed the subtle color change.

**How to apply:** If a symptom report seems inconsistent with what the code should be doing, formulate a question rather than a fix. Confirm first, implement second.
