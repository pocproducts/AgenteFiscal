# Conversation Deletion Specification

## Purpose

Deletion that sticks: hard delete with no re-creation via title saves or upserts, honest 404 semantics, and explicit client-side error handling with invalidation and navigation of the active chat.

## Requirements

### Requirement: CD-1 — Deleted conversations stay deleted

The backend MUST hard-delete the conversation row on `DELETE /v1/conversations/{id}`. A deleted conversation MUST NOT reappear on reload, revalidation, or sidebar remount.

#### Scenario: Delete then reload

- GIVEN an existing conversation
- WHEN the user deletes it and then reloads the sidebar
- THEN the conversation is gone
- AND it does not reappear on subsequent revalidation

#### Scenario: Second delete returns honest 404

- GIVEN a conversation that was already deleted
- WHEN DELETE is called again
- THEN the response is a 404 indicating the conversation does not exist
- AND the response marks `deleted: false` instead of reporting success

### Requirement: CD-2 — Title save never creates or resurrects rows

The title-save path MUST NOT create a conversation row; saving a title for a non-existent conversation MUST NOT insert it. The stream upsert MUST NOT resurrect a conversation that was explicitly deleted.

#### Scenario: Title save on a deleted chat does not resurrect

- GIVEN a deleted conversation still referenced by the client
- WHEN the client saves a title for it
- THEN no conversation row is created
- AND the conversation remains deleted

#### Scenario: Upsert refused for deleted conversations

- GIVEN a deleted conversation still open in the UI
- WHEN a new message turn triggers the conversation upsert
- THEN the conversation is not re-created
- AND the turn surfaces the missing-conversation result instead

### Requirement: CD-3 — Honest 404 semantics

The BFF MUST map a backend 404 to a real failure response (e.g. `{ success: false, deleted: false }`) instead of swallowing it as a successful no-op. The client MUST handle that response without hiding the row from the list.

#### Scenario: BFF propagates 404

- GIVEN a DELETE request for a conversation the user cannot delete (missing or wrong tenant)
- WHEN the backend returns 404
- THEN the BFF returns `deleted: false`
- AND the sidebar does not report success

### Requirement: CD-4 — Client awaits delete, toasts errors, invalidates, navigates

The client MUST await the DELETE request, MUST surface a visible error toast on failure, and on success MUST invalidate the history list and, when the deleted chat is the active one, navigate away or clear the active state.

#### Scenario: Success path

- GIVEN an active conversation in the sidebar
- WHEN the user deletes it and the request succeeds
- THEN the row is removed from the list and history is invalidated
- AND if it was the active chat, the app navigates away or clears active state

#### Scenario: Failure path

- GIVEN a network error or 5xx on the DELETE request
- WHEN the request fails
- THEN an error toast is shown
- AND the sidebar reconciles to server truth instead of optimistically dropping the row