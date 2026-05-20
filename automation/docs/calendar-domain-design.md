# Calendar Domain Design Document

**Status:** Ready for implementation
**Date:** 2026-02-19
**Author:** Calendar Domain Planner agent
**Target:** Builder Dev agent — pick this up and build from top to bottom

---

## Table of Contents

1. [Domain Overview](#1-domain-overview)
2. [n8n Google Calendar Node Specs](#2-n8n-google-calendar-node-specs)
3. [Credential Setup](#3-credential-setup)
4. [Workflow Inventory](#4-workflow-inventory)
5. [Per-Workflow Specifications](#5-per-workflow-specifications)
6. [Calendar.FindFreeSlot — Code Algorithm](#6-calendarfindfreeSlot--code-algorithm)
7. [Registry Entries (Ready to Paste)](#7-registry-entries-ready-to-paste)
8. [nodeWhitelist Update Required](#8-nodewhitelist-update-required)
9. [Build Order](#9-build-order)
10. [Edge Cases and Gotchas](#10-edge-cases-and-gotchas)

---

## 1. Domain Overview

The Calendar domain gives the Nexus orchestration layer full read/write control over Google Calendar. An AI agent with Calendar access can schedule meetings, check availability before booking, look up what's coming up, modify or cancel events, and enumerate which calendars are available.

The credential used is `gmail_main` — the same Google OAuth2 credential already deployed for the Email domain. This credential was granted the full Google suite scope (`https://www.googleapis.com/auth/calendar`), so no new credential setup is required.

Seven workflows are defined:

| # | Name | Dangerous | Description |
|---|------|-----------|-------------|
| 1 | `Calendar.ListCalendars` | No | List all calendars the authenticated user has access to |
| 2 | `Calendar.List` | No | List upcoming events with optional date range, calendar, and text filters |
| 3 | `Calendar.Get` | No | Retrieve a single event by ID |
| 4 | `Calendar.Create` | No | Create a new calendar event |
| 5 | `Calendar.Update` | No | Modify fields on an existing event |
| 6 | `Calendar.Delete` | **Yes** | Permanently delete a calendar event |
| 7 | `Calendar.FindFreeSlot` | No | Find available time slots given a duration and search window |

---

## 2. n8n Google Calendar Node Specs

### Node Identity

```
workflowNodeType: "n8n-nodes-base.googleCalendar"
displayName:      "Google Calendar"
typeVersion:      1.3      ← ALWAYS use 1.3 (latest verified)
package:          n8n-nodes-base
credentialType:   googleCalendarOAuth2Api
```

The MCP node database notes: **"Use typeVersion: 1.3 when creating this node"**.

### Resources and Operations

The node has two top-level resources: `event` and `calendar`.

#### Resource: `event`

| Operation | n8n operation value | Notes |
|-----------|--------------------|----|
| Create | `create` | Creates a new event |
| Get | `get` | Fetches one event by eventId |
| Get Many | `getAll` | Lists events; supports date range + text filters |
| Update | `update` | Patches fields on an existing event |
| Delete | `delete` | Hard-deletes an event |

#### Resource: `calendar`

| Operation | n8n operation value | Notes |
|-----------|--------------------|----|
| Availability | `availability` | Returns free/busy blocks in a given time window |

There is **no native "list calendars" operation** in the n8n Google Calendar node. `Calendar.ListCalendars` must be implemented using an **HTTP Request node** calling `GET https://www.googleapis.com/calendar/v3/users/me/calendarList` with `predefinedCredentialType: "googleCalendarOAuth2Api"`. This mirrors the same pattern used for `Email.Label` (Gmail HTTP workaround).

There is **no native "find free slot" operation**. `Calendar.FindFreeSlot` uses the `calendar` resource `availability` operation to get busy blocks, then a Code node computes the free slots. See Section 6 for the algorithm.

### Key Parameters by Operation

#### `event` / `create`

| Parameter | Type | Required | Notes |
|-----------|------|----------|-------|
| `calendar` | resourceLocator | Yes | `{ mode: "id", value: "primary" }` for primary calendar |
| `start` | dateTime | Yes | ISO 8601 string |
| `end` | dateTime | Yes | ISO 8601 string |
| `summary` | string | No* | Event title. Technically optional in API; treat as required in our schema |
| `description` | string | No | Plain text or HTML |
| `location` | string | No | Free-text location |
| `attendees` | array | No | Array of `{ email: "..." }` objects |
| `recurrence` | array | No | RRULE strings, e.g. `["RRULE:FREQ=WEEKLY;COUNT=5"]` |
| `colorId` | string | No | Integer 1–11 as string |
| `status` | options | No | `"confirmed"` (default), `"tentative"`, `"cancelled"` |
| `visibility` | options | No | `"default"`, `"public"`, `"private"`, `"confidential"` |
| `sendUpdates` | options | No | `"all"`, `"externalOnly"`, `"none"` (default `"all"`) — controls invite emails |
| `conferenceDataVersion` | number | No | Set to `1` to trigger Meet link creation |

#### `event` / `get`

| Parameter | Type | Required |
|-----------|------|----------|
| `calendar` | resourceLocator | Yes |
| `eventId` | string | Yes |

#### `event` / `getAll`

| Parameter | Type | Required | Notes |
|-----------|------|----------|-------|
| `calendar` | resourceLocator | Yes | |
| `timeMin` | dateTime | No | Lower bound for event start time |
| `timeMax` | dateTime | No | Upper bound for event start time |
| `q` | string | No | Free-text search across summary, description, location, attendee display names |
| `maxResults` | number | No | Default 250; cap at 2500 |
| `singleEvents` | boolean | No | `true` expands recurring events into individual instances |
| `orderBy` | options | No | `"startTime"` (requires singleEvents=true) or `"updated"` |
| `showDeleted` | boolean | No | Include cancelled events |

#### `event` / `update`

Same parameters as `create`, plus:

| Parameter | Type | Required |
|-----------|------|----------|
| `eventId` | string | Yes |

Only fields provided are patched; omitted fields are left unchanged.

#### `event` / `delete`

| Parameter | Type | Required |
|-----------|------|----------|
| `calendar` | resourceLocator | Yes |
| `eventId` | string | Yes |
| `sendUpdates` | options | No | Controls cancellation notification emails. Default `"all"`. |

#### `calendar` / `availability`

| Parameter | Type | Required | Notes |
|-----------|------|----------|-------|
| `calendar` | resourceLocator | Yes | |
| `timeMin` | dateTime | Yes | Start of the query window |
| `timeMax` | dateTime | Yes | End of the query window |
| `timezone` | string | No | IANA timezone (e.g., `"US/Central"`). If omitted, UTC is used |

**Output shape**: Returns an object with a `busy` array, where each element is `{ start: "ISO", end: "ISO" }` representing a busy block within the window. If the calendar is completely free, `busy` is an empty array.

### Node JSON Template (for Builder to copy)

```json
{
  "id": "REPLACE_ME",
  "name": "REPLACE_ME",
  "type": "n8n-nodes-base.googleCalendar",
  "typeVersion": 1.3,
  "position": [0, 0],
  "parameters": {
    "resource": "event",
    "operation": "create",
    "calendar": {
      "mode": "id",
      "value": "={{ $json.calendarId || 'primary' }}"
    },
    "start": "={{ $json.start }}",
    "end": "={{ $json.end }}",
    "additionalFields": {
      "summary": "={{ $json.title }}",
      "description": "={{ $json.description }}",
      "location": "={{ $json.location }}"
    }
  },
  "credentials": {
    "googleCalendarOAuth2Api": {
      "id": "6IGQz4SKT7kp908J",
      "name": "Gmail account"
    }
  }
}
```

**Credential note:** The Google Calendar credential uses the same OAuth2 token as Gmail (`id: "6IGQz4SKT7kp908J"`, name `"Gmail account"`). The credential type for Calendar is `googleCalendarOAuth2Api` but the credential ID in n8n is the same object — Google OAuth2 scopes are combined per credential. Confirm this is still the case in the running instance before building; if a separate Calendar-only credential exists, use that ID instead.

---

## 3. Credential Setup

No new credentials need to be created. The `gmail_main` credential (`id: 6IGQz4SKT7kp908J`, scope: full Google suite) already has Calendar access. All Calendar workflows set `credentialRef: "gmail_main"` in the registry.

In n8n workflow JSON, reference it as:
```json
"credentials": {
  "googleCalendarOAuth2Api": {
    "id": "6IGQz4SKT7kp908J",
    "name": "Gmail account"
  }
}
```

---

## 4. Workflow Inventory

### Standard 4-Node Pattern

All Calendar workflows follow the same structure as the Email domain:

```
Execute Workflow Trigger → Validate Input (Code) → Operation (Calendar node or HTTP) → Format Output (Set)
```

For `Calendar.FindFreeSlot` the pattern extends to 5 nodes (availability fetch + code computation):

```
Execute Workflow Trigger → Validate Input (Code) → Get Busy Blocks (Calendar) → Find Free Slots (Code) → Format Output (Set)
```

### calendarId Handling

Every operation that touches a specific calendar requires a `calendarId`. The special value `"primary"` refers to the user's primary calendar and is the default. All input schemas include `calendarId` as an optional field defaulting to `"primary"`. The Validate Input node should default it: `const calendarId = $json.calendarId || 'primary';`.

### Date/Time Conventions

- All date/time inputs and outputs use **ISO 8601 format** (`2026-02-19T14:00:00-06:00` or `2026-02-19T20:00:00Z`).
- The system timezone is `US/Central`. Workflows should preserve whatever timezone the caller passes in. When generating default time windows (e.g., "next 7 days"), use `$now` in Luxon expressions.
- The Google Calendar node's `dateTime` type fields accept ISO 8601 strings directly when set via expression.

---

## 5. Per-Workflow Specifications

---

### 5.1 Calendar.ListCalendars

**Description:** List all Google Calendars the authenticated user has access to.

**Implementation:** HTTP Request node (not the Calendar node — no native list-calendars operation exists).

```
Execute Workflow Trigger → Validate Input (Code) → List Calendars (HTTP Request) → Format Output (Set)
```

**HTTP Request node config:**
```json
{
  "method": "GET",
  "url": "https://www.googleapis.com/calendar/v3/users/me/calendarList",
  "authentication": "predefinedCredentialType",
  "nodeCredentialType": "googleCalendarOAuth2Api",
  "options": {}
}
```

Query parameter `maxResults` defaults to 100 (API max 250). Optional `showHidden=true` to include hidden calendars.

**Input schema:**
```
showHidden  boolean  optional  Include hidden/unsubscribed calendars (default false)
```

**Output schema:**
```
calendars  array  Array of calendar summary objects
  Each item:
    calendarId    string  Unique calendar ID (use this as input to other Calendar.* workflows)
    name          string  Human-readable calendar name (from "summary" field in API)
    description   string  Calendar description (may be null)
    timezone      string  IANA timezone of the calendar
    accessRole    string  "owner" | "writer" | "reader" | "freeBusyReader"
    primary       boolean  true if this is the user's primary calendar
    backgroundColor  string  Hex color of the calendar in UI
count      number  Total number of calendars returned
```

**Format Output (Set node):**
```javascript
// In Code node to shape output:
const raw = $json.items || [];
const calendars = raw.map(c => ({
  calendarId: c.id,
  name: c.summary,
  description: c.description || null,
  timezone: c.timeZone,
  accessRole: c.accessRole,
  primary: c.primary || false,
  backgroundColor: c.backgroundColor || null
}));
return [{ json: { calendars, count: calendars.length } }];
```

**Tags:** `["calendar", "google-calendar", "list", "meta"]`
**dangerous:** false

---

### 5.2 Calendar.List

**Description:** List upcoming calendar events with optional date range, calendar ID, and text search filters.

**Implementation:** Google Calendar node, resource: `event`, operation: `getAll`.

```
Execute Workflow Trigger → Validate Input (Code) → Get Events (googleCalendar getAll) → Format Output (Set)
```

**Input schema:**
```
calendarId   string   optional  Calendar ID to query (default "primary")
timeMin      string   optional  ISO 8601 start bound (default: now)
timeMax      string   optional  ISO 8601 end bound (default: now + 7 days)
query        string   optional  Free-text search (title, description, location, attendees)
limit        number   optional  Max events to return (default 10, max 100)
singleEvents boolean  optional  Expand recurring events into instances (default true)
```

**Output schema:**
```
events   array   Array of event summary objects
  Each item:
    eventId      string  Google Calendar event ID
    calendarId   string  Calendar this event belongs to
    title        string  Event summary/title
    start        string  ISO 8601 start datetime
    end          string  ISO 8601 end datetime
    location     string  Location (null if not set)
    description  string  Description (null if not set)
    status       string  "confirmed" | "tentative" | "cancelled"
    attendeeCount  number  Number of attendees
    isRecurring  boolean  True if part of a recurring series
    htmlLink     string  URL to open event in Google Calendar web UI
count    number   Total events returned
```

**Validate Input code logic:**
```javascript
const { calendarId, timeMin, timeMax, query, limit, singleEvents } = $json;
const errors = [];
if (limit !== undefined && (typeof limit !== 'number' || limit < 1 || limit > 100)) {
  errors.push('limit must be a number between 1 and 100');
}
if (errors.length) throw new Error(errors.join('; '));
return [{
  json: {
    calendarId: calendarId || 'primary',
    timeMin: timeMin || $now.toISO(),
    timeMax: timeMax || $now.plus({ days: 7 }).toISO(),
    query: query || undefined,
    limit: limit || 10,
    singleEvents: singleEvents !== false
  }
}];
```

**Format Output — flatten the getAll response:**
```javascript
const items = $input.all();
const events = items.map(item => {
  const e = item.json;
  return {
    eventId: e.id,
    calendarId: e.calendarId || 'primary',
    title: e.summary || '(No title)',
    start: e.start?.dateTime || e.start?.date,
    end: e.end?.dateTime || e.end?.date,
    location: e.location || null,
    description: e.description || null,
    status: e.status,
    attendeeCount: (e.attendees || []).length,
    isRecurring: !!e.recurringEventId,
    htmlLink: e.htmlLink
  };
});
return [{ json: { events, count: events.length } }];
```

**Tags:** `["calendar", "google-calendar", "list", "events", "schedule"]`
**dangerous:** false

---

### 5.3 Calendar.Get

**Description:** Retrieve a single calendar event by its event ID.

**Implementation:** Google Calendar node, resource: `event`, operation: `get`.

```
Execute Workflow Trigger → Validate Input (Code) → Get Event (googleCalendar get) → Format Output (Set)
```

**Input schema:**
```
eventId     string   required  Google Calendar event ID
calendarId  string   optional  Calendar containing the event (default "primary")
```

**Output schema:**
```
eventId        string   Google Calendar event ID
calendarId     string   Calendar ID
title          string   Event title
start          string   ISO 8601 start datetime
end            string   ISO 8601 end datetime
location       string   Location (null if not set)
description    string   Description (null if not set)
status         string   "confirmed" | "tentative" | "cancelled"
attendees      array    Array of { email, displayName, responseStatus }
organizer      object   { email, displayName }
isRecurring    boolean  True if part of a recurring series
recurrenceRule array    RRULE strings (null if not recurring)
created        string   ISO 8601 creation timestamp
updated        string   ISO 8601 last-modified timestamp
htmlLink       string   URL to open in Google Calendar web UI
conferenceData object   Meet link info (null if no video conference attached)
```

**Tags:** `["calendar", "google-calendar", "get", "event"]`
**dangerous:** false

---

### 5.4 Calendar.Create

**Description:** Create a new Google Calendar event with title, start time, and end time; optionally add description, location, attendees, and recurrence.

**Implementation:** Google Calendar node, resource: `event`, operation: `create`.

```
Execute Workflow Trigger → Validate Input (Code) → Create Event (googleCalendar create) → Format Output (Set)
```

**Input schema:**
```
title          string   required  Event title (summary)
start          string   required  ISO 8601 start datetime
end            string   required  ISO 8601 end datetime
calendarId     string   optional  Target calendar ID (default "primary")
description    string   optional  Event description (plain text or HTML)
location       string   optional  Event location (free text or address)
attendees      array    optional  Array of email address strings ["a@b.com", "c@d.com"]
recurrence     array    optional  RRULE strings ["RRULE:FREQ=WEEKLY;BYDAY=MO;COUNT=4"]
sendUpdates    string   optional  "all" | "externalOnly" | "none" (default "all")
conferenceData boolean  optional  If true, attach a Google Meet link (default false)
colorId        string   optional  Calendar color code "1"–"11"
visibility     string   optional  "default" | "public" | "private" | "confidential"
```

**Output schema:**
```
eventId      string   Newly created event ID
calendarId   string   Calendar where the event was created
title        string   Event title as saved
start        string   ISO 8601 start datetime
end          string   ISO 8601 end datetime
htmlLink     string   URL to open event in Google Calendar web UI
meetLink     string   Google Meet join URL (null if conferenceData was false)
status       string   "confirmed"
```

**Validate Input code logic (critical checks):**
```javascript
const { title, start, end } = $json;
const errors = [];
if (!title || typeof title !== 'string') errors.push('title is required');
if (!start) errors.push('start is required');
if (!end) errors.push('end is required');
if (start && end && new Date(end) <= new Date(start)) {
  errors.push('end must be after start');
}
if (errors.length) throw new Error(errors.join('; '));
// Normalize attendees: accept array of strings or array of {email} objects
const raw = $json.attendees || [];
const attendees = raw.map(a => typeof a === 'string' ? { email: a } : a);
return [{ json: { ...$json, attendees } }];
```

**Builder note on conferenceData:** To attach a Meet link, set `conferenceDataVersion: 1` on the node and include a `conferenceData.createRequest` in additionalFields. This requires an extra calendar API call internally and Google may take a few seconds to provision the link — the returned URL is in `conferenceData.entryPoints[0].uri`.

**Tags:** `["calendar", "google-calendar", "create", "event", "schedule", "book"]`
**dangerous:** false

---

### 5.5 Calendar.Update

**Description:** Modify fields on an existing calendar event; only supplied fields are changed, all others are preserved.

**Implementation:** Google Calendar node, resource: `event`, operation: `update`.

```
Execute Workflow Trigger → Validate Input (Code) → Update Event (googleCalendar update) → Format Output (Set)
```

**Input schema:**
```
eventId        string   required  Event ID to update
calendarId     string   optional  Calendar containing the event (default "primary")
title          string   optional  New event title
start          string   optional  New ISO 8601 start datetime
end            string   optional  New ISO 8601 end datetime
description    string   optional  New description
location       string   optional  New location
attendees      array    optional  New attendee email list (REPLACES existing list entirely)
sendUpdates    string   optional  "all" | "externalOnly" | "none" (default "all")
status         string   optional  "confirmed" | "tentative" | "cancelled"
visibility     string   optional  "default" | "public" | "private" | "confidential"
```

**Output schema:**
```
eventId      string   Event ID
calendarId   string   Calendar ID
title        string   Updated title
start        string   Updated start datetime
end          string   Updated end datetime
htmlLink     string   URL to open in Google Calendar web UI
updated      string   ISO 8601 timestamp of this update
```

**Critical gotcha — attendees field:** The update operation on the Google Calendar API REPLACES the attendees list, not merges it. If the caller only wants to add one attendee, they must first `Calendar.Get` the event, append to the attendees list, then call `Calendar.Update` with the full merged list. Document this clearly in the semanticDescription.

**Tags:** `["calendar", "google-calendar", "update", "event", "modify"]`
**dangerous:** false

---

### 5.6 Calendar.Delete

**Description:** Permanently delete a calendar event by ID. This action is irreversible and triggers cancellation notifications to all attendees by default.

**Implementation:** Google Calendar node, resource: `event`, operation: `delete`.

```
Execute Workflow Trigger → Validate Input (Code) → Delete Event (googleCalendar delete) → Format Output (Set)
```

**DANGEROUS ACTION — requires `confirm_dangerous: true` from Nexus.Orchestrator.**

**Input schema:**
```
eventId        string   required  Event ID to delete
calendarId     string   optional  Calendar containing the event (default "primary")
sendUpdates    string   optional  Cancellation notification mode: "all" (default), "externalOnly", "none"
```

**Output schema:**
```
eventId    string   The event ID that was deleted
status     string   "deleted"
```

**Format Output note:** The Google Calendar delete endpoint returns HTTP 204 No Content — the n8n node returns an empty item. The Format Output Set node must construct the confirmation object explicitly using the input values, not from the operation's output:
```javascript
return [{
  json: {
    eventId: $('Validate Input').first().json.eventId,
    status: 'deleted'
  }
}];
```

**Tags:** `["calendar", "google-calendar", "delete", "event", "dangerous"]`
**dangerous:** true

---

### 5.7 Calendar.FindFreeSlot

**Description:** Find available time slots of a specified duration within a search window, filtered to working hours.

**Implementation:** 5-node pattern — uses the `calendar` resource `availability` operation to get busy blocks, then a Code node applies the free-slot algorithm.

```
Execute Workflow Trigger → Validate Input (Code) → Get Busy Blocks (googleCalendar availability) → Find Free Slots (Code) → Format Output (Set)
```

**There is no native FindFreeSlot operation in the n8n Google Calendar node.** The `calendar` / `availability` operation returns a list of BUSY time blocks. The Code node then computes the inverse: the gaps between busy blocks that are long enough to fit the requested duration and fall within working hours.

**Input schema:**
```
durationMinutes  number   required  Slot length needed in minutes (e.g., 30, 60)
searchStart      string   optional  ISO 8601 start of search window (default: now)
searchEnd        string   optional  ISO 8601 end of search window (default: now + 7 days)
calendarId       string   optional  Calendar to check (default "primary")
workdayStartHour number   optional  Working day start hour in local time (default 9)
workdayEndHour   number   optional  Working day end hour in local time (default 17)
timezone         string   optional  IANA timezone for workday bounds (default "US/Central")
maxSlots         number   optional  Max free slots to return (default 5)
```

**Output schema:**
```
slots     array    Array of available time slot objects
  Each item:
    start         string   ISO 8601 start of available slot
    end           string   ISO 8601 end of available slot (start + durationMinutes)
    durationMinutes  number  Duration of this slot
count     number   Number of free slots found
searched  object   { from: ISO, to: ISO } — the window that was searched
```

**Tags:** `["calendar", "google-calendar", "availability", "scheduling", "free-slot", "find"]`
**dangerous:** false

See Section 6 for the full Code node algorithm.

---

## 6. Calendar.FindFreeSlot — Code Algorithm

The Google Calendar node's `availability` operation returns busy blocks. The Code node in step 4 must implement the following logic:

```javascript
// Node: "Find Free Slots"
// Input: $('Validate Input').first().json has: durationMinutes, searchStart, searchEnd,
//        workdayStartHour, workdayEndHour, timezone, maxSlots
// Input: $('Get Busy Blocks').first().json has: busy: [{start, end}, ...]

const params = $('Validate Input').first().json;
const { durationMinutes, workdayStartHour, workdayEndHour, timezone, maxSlots } = params;

// Get busy blocks from availability node
const busyData = $('Get Busy Blocks').first().json;
const busyBlocks = (busyData.busy || []).map(b => ({
  start: new Date(b.start).getTime(),
  end: new Date(b.end).getTime()
})).sort((a, b) => a.start - b.start);

const windowStart = new Date(params.searchStart).getTime();
const windowEnd   = new Date(params.searchEnd).getTime();
const durationMs  = durationMinutes * 60 * 1000;
const slots = [];

// Build candidate free blocks by inverting busy blocks within the window
const freeBlocks = [];
let cursor = windowStart;
for (const busy of busyBlocks) {
  if (busy.start > cursor) {
    freeBlocks.push({ start: cursor, end: busy.start });
  }
  if (busy.end > cursor) cursor = busy.end;
}
if (cursor < windowEnd) {
  freeBlocks.push({ start: cursor, end: windowEnd });
}

// Helper: given a UTC timestamp, get the local hour in the target timezone
function getLocalHour(tsMs, tz) {
  // Use Intl.DateTimeFormat to get the hour in the target timezone
  const fmt = new Intl.DateTimeFormat('en-US', {
    hour: 'numeric',
    hour12: false,
    timeZone: tz
  });
  const parts = fmt.formatToParts(new Date(tsMs));
  return parseInt(parts.find(p => p.type === 'hour').value, 10);
}

// Helper: clamp a free block to working hours on a given calendar day
// Returns array of {start, end} sub-blocks that fall within workday hours
function clampToWorkday(blockStart, blockEnd, wdStart, wdEnd, tz) {
  const subBlocks = [];
  // Iterate over each calendar day touched by this block
  let dayStart = new Date(blockStart);
  dayStart.setUTCHours(0, 0, 0, 0);  // Approximate; refine per day below

  // Simpler approach: walk in 15-minute increments looking for qualifying slots
  // This avoids complex timezone DST math in n8n's JS environment
  const step = 15 * 60 * 1000; // 15-minute granularity
  let t = blockStart;
  let subStart = null;

  while (t < blockEnd) {
    const hour = getLocalHour(t, tz);
    const inWorkday = hour >= wdStart && hour < wdEnd;
    if (inWorkday && subStart === null) {
      subStart = t;
    } else if (!inWorkday && subStart !== null) {
      subBlocks.push({ start: subStart, end: t });
      subStart = null;
    }
    t += step;
  }
  if (subStart !== null && t <= blockEnd) {
    subBlocks.push({ start: subStart, end: blockEnd });
  }
  return subBlocks;
}

// For each free block, clamp to working hours and collect durationMs-sized slots
for (const freeBlock of freeBlocks) {
  if (slots.length >= maxSlots) break;

  const workdaySubBlocks = clampToWorkday(
    freeBlock.start, freeBlock.end,
    workdayStartHour, workdayEndHour, timezone
  );

  for (const sub of workdaySubBlocks) {
    if (slots.length >= maxSlots) break;
    // Slide a window of durationMs across this sub-block
    // Align to next 15-minute boundary for cleaner times
    const align = 15 * 60 * 1000;
    let slotStart = Math.ceil(sub.start / align) * align;
    while (slotStart + durationMs <= sub.end) {
      slots.push({
        start: new Date(slotStart).toISOString(),
        end:   new Date(slotStart + durationMs).toISOString(),
        durationMinutes
      });
      slotStart += align;
      if (slots.length >= maxSlots) break;
    }
  }
}

return [{
  json: {
    slots,
    count: slots.length,
    searched: {
      from: new Date(windowStart).toISOString(),
      to:   new Date(windowEnd).toISOString()
    }
  }
}];
```

**Algorithm notes:**
- The 15-minute walk for timezone clamping is intentionally simple — it avoids the complexity of computing exact UTC midnight offsets per day per timezone. For a search window of 7 days it processes at most 672 steps (7 * 24 * 4), which is well within Code node performance limits.
- Slots are aligned to 15-minute boundaries (e.g., 9:00, 9:15, 9:30) so suggestions look clean.
- The `maxSlots` cap prevents returning hundreds of slots for a free calendar over a long window.
- Weekend days are NOT explicitly excluded by default — the workday hour clamping means if `workdayStartHour=9` and `workdayEndHour=17`, slots on Saturday and Sunday 9–17 will be included. If the caller wants weekdays only, a future enhancement can add a `weekdaysOnly` boolean input; the Code node would add `const dayOfWeek = new Date(t).getDay(); if (dayOfWeek === 0 || dayOfWeek === 6) { subStart = null; continue; }`.
- The `availability` node call requires `timeMin` and `timeMax` set to the full search window. Pass `searchStart` and `searchEnd` from Validate Input into those fields via expression.

---

## 7. Registry Entries (Ready to Paste)

These entries are ready to be added to `workflow-registry.json` under the `"workflows"` key. All have `"n8nId": null` — fill in the ID after deployment.

```json
"Calendar.ListCalendars": {
  "n8nId": null,
  "description": "List all Google Calendars the authenticated user has access to",
  "semanticDescription": "Returns the full list of Google Calendars associated with the authenticated account, including personal calendars, shared calendars, and subscribed calendars. Each entry includes the calendar ID (needed by all other Calendar.* workflows), display name, timezone, access role, and whether it is the primary calendar. Use this workflow before any other Calendar operation when you do not already know the calendarId, or when the user asks 'which calendars do I have'. Takes no required inputs.",
  "input": {
    "showHidden": {
      "type": "boolean",
      "required": false,
      "description": "Include hidden or unsubscribed calendars (default false)"
    }
  },
  "output": {
    "calendars": {
      "type": "array",
      "description": "Array of { calendarId, name, description, timezone, accessRole, primary, backgroundColor }"
    },
    "count": {
      "type": "number",
      "description": "Total number of calendars returned"
    }
  },
  "tags": ["calendar", "google-calendar", "list", "meta"],
  "credentialRef": "gmail_main",
  "dangerous": false,
  "status": "inactive",
  "version": 1,
  "createdBy": "claude-code",
  "nodeHash": null,
  "usageCount": 0,
  "lastVerified": null,
  "dependsOn": [],
  "allowedCallers": "any"
},

"Calendar.List": {
  "n8nId": null,
  "description": "List upcoming Google Calendar events with optional date range, calendar, and text filters",
  "semanticDescription": "Queries a Google Calendar for events within a time window and returns a list of event summaries including title, start, end, location, and attendee count. Use this to answer questions like 'what do I have coming up this week' or 'show me all meetings tomorrow'. All inputs are optional — calling with no parameters returns the next 10 events on the primary calendar over the next 7 days. For a single specific event when you already have its ID, use Calendar.Get instead. For finding open time in the calendar, use Calendar.FindFreeSlot.",
  "input": {
    "calendarId":   { "type": "string",  "required": false, "description": "Calendar ID to query (default: 'primary')" },
    "timeMin":      { "type": "string",  "required": false, "description": "ISO 8601 lower bound for event start (default: now)" },
    "timeMax":      { "type": "string",  "required": false, "description": "ISO 8601 upper bound for event start (default: now + 7 days)" },
    "query":        { "type": "string",  "required": false, "description": "Free-text search across title, description, location, attendee names" },
    "limit":        { "type": "number",  "required": false, "description": "Max events to return (default 10, max 100)" },
    "singleEvents": { "type": "boolean", "required": false, "description": "Expand recurring events into individual instances (default true)" }
  },
  "output": {
    "events": {
      "type": "array",
      "description": "Array of { eventId, calendarId, title, start, end, location, description, status, attendeeCount, isRecurring, htmlLink }"
    },
    "count": { "type": "number", "description": "Total events returned" }
  },
  "tags": ["calendar", "google-calendar", "list", "events", "schedule"],
  "credentialRef": "gmail_main",
  "dangerous": false,
  "status": "inactive",
  "version": 1,
  "createdBy": "claude-code",
  "nodeHash": null,
  "usageCount": 0,
  "lastVerified": null,
  "dependsOn": [],
  "allowedCallers": "any"
},

"Calendar.Get": {
  "n8nId": null,
  "description": "Get a single Google Calendar event by ID",
  "semanticDescription": "Retrieves the complete details of one specific Google Calendar event by its event ID, including all attendees, the organizer, full description, location, recurrence rule, conference (Meet) link, and timestamps. Use this when you have a known event ID and need full event details. For browsing upcoming events without a known ID, use Calendar.List or Calendar.FindFreeSlot instead. The eventId comes from the output of Calendar.List, Calendar.Create, or Calendar.Update.",
  "input": {
    "eventId":    { "type": "string", "required": true,  "description": "Google Calendar event ID" },
    "calendarId": { "type": "string", "required": false, "description": "Calendar containing the event (default: 'primary')" }
  },
  "output": {
    "eventId":       { "type": "string",  "description": "Event ID" },
    "calendarId":    { "type": "string",  "description": "Calendar ID" },
    "title":         { "type": "string",  "description": "Event title" },
    "start":         { "type": "string",  "description": "ISO 8601 start datetime" },
    "end":           { "type": "string",  "description": "ISO 8601 end datetime" },
    "location":      { "type": "string",  "description": "Event location (null if not set)" },
    "description":   { "type": "string",  "description": "Event description (null if not set)" },
    "status":        { "type": "string",  "description": "'confirmed' | 'tentative' | 'cancelled'" },
    "attendees":     { "type": "array",   "description": "Array of { email, displayName, responseStatus }" },
    "organizer":     { "type": "object",  "description": "{ email, displayName }" },
    "isRecurring":   { "type": "boolean", "description": "True if part of a recurring series" },
    "recurrenceRule":{ "type": "array",   "description": "RRULE strings (null if not recurring)" },
    "created":       { "type": "string",  "description": "ISO 8601 creation timestamp" },
    "updated":       { "type": "string",  "description": "ISO 8601 last-modified timestamp" },
    "htmlLink":      { "type": "string",  "description": "URL to open event in Google Calendar web UI" },
    "conferenceData":{ "type": "object",  "description": "Meet link info (null if no video conference)" }
  },
  "tags": ["calendar", "google-calendar", "get", "event"],
  "credentialRef": "gmail_main",
  "dangerous": false,
  "status": "inactive",
  "version": 1,
  "createdBy": "claude-code",
  "nodeHash": null,
  "usageCount": 0,
  "lastVerified": null,
  "dependsOn": [],
  "allowedCallers": "any"
},

"Calendar.Create": {
  "n8nId": null,
  "description": "Create a new Google Calendar event",
  "semanticDescription": "Creates a new event on Google Calendar with a title, start time, and end time. Supports optional description, location, attendee list, recurrence rules, Google Meet link generation, and color coding. Sending invitations to attendees is controlled by the sendUpdates field (default 'all' — attendees receive email invitations). Use this when the goal is to book a new meeting, appointment, or reminder. Do NOT use this to modify an existing event — use Calendar.Update. If you need to first check availability before creating, call Calendar.FindFreeSlot first then pass the chosen slot to this workflow.",
  "input": {
    "title":          { "type": "string",  "required": true,  "description": "Event title (summary)" },
    "start":          { "type": "string",  "required": true,  "description": "ISO 8601 start datetime" },
    "end":            { "type": "string",  "required": true,  "description": "ISO 8601 end datetime" },
    "calendarId":     { "type": "string",  "required": false, "description": "Target calendar ID (default: 'primary')" },
    "description":    { "type": "string",  "required": false, "description": "Event description (plain text or HTML)" },
    "location":       { "type": "string",  "required": false, "description": "Event location" },
    "attendees":      { "type": "array",   "required": false, "description": "Array of attendee email address strings" },
    "recurrence":     { "type": "array",   "required": false, "description": "RRULE strings, e.g. ['RRULE:FREQ=WEEKLY;COUNT=4']" },
    "sendUpdates":    { "type": "string",  "required": false, "description": "'all' | 'externalOnly' | 'none' (default 'all')" },
    "conferenceData": { "type": "boolean", "required": false, "description": "If true, attach a Google Meet link" },
    "colorId":        { "type": "string",  "required": false, "description": "Calendar color code '1'–'11'" },
    "visibility":     { "type": "string",  "required": false, "description": "'default' | 'public' | 'private' | 'confidential'" }
  },
  "output": {
    "eventId":    { "type": "string", "description": "Newly created event ID" },
    "calendarId": { "type": "string", "description": "Calendar where event was created" },
    "title":      { "type": "string", "description": "Event title as saved" },
    "start":      { "type": "string", "description": "ISO 8601 start datetime" },
    "end":        { "type": "string", "description": "ISO 8601 end datetime" },
    "htmlLink":   { "type": "string", "description": "URL to open event in Google Calendar web UI" },
    "meetLink":   { "type": "string", "description": "Google Meet join URL (null if conferenceData was false)" },
    "status":     { "type": "string", "description": "'confirmed'" }
  },
  "tags": ["calendar", "google-calendar", "create", "event", "schedule", "book"],
  "credentialRef": "gmail_main",
  "dangerous": false,
  "status": "inactive",
  "version": 1,
  "createdBy": "claude-code",
  "nodeHash": null,
  "usageCount": 0,
  "lastVerified": null,
  "dependsOn": [],
  "allowedCallers": "any"
},

"Calendar.Update": {
  "n8nId": null,
  "description": "Modify fields on an existing Google Calendar event",
  "semanticDescription": "Updates one or more fields on an existing Google Calendar event identified by its event ID. Only the fields provided in the input are changed — all other fields are preserved (patch semantics). Can change the title, start/end time, description, location, status, visibility, or attendee list. WARNING: the attendees field replaces the entire attendee list, not merges with it — if adding one attendee, first call Calendar.Get to retrieve the current list, then pass the full updated list to this workflow. Use Calendar.Delete to remove an event entirely.",
  "input": {
    "eventId":     { "type": "string", "required": true,  "description": "Event ID to update" },
    "calendarId":  { "type": "string", "required": false, "description": "Calendar containing the event (default: 'primary')" },
    "title":       { "type": "string", "required": false, "description": "New event title" },
    "start":       { "type": "string", "required": false, "description": "New ISO 8601 start datetime" },
    "end":         { "type": "string", "required": false, "description": "New ISO 8601 end datetime" },
    "description": { "type": "string", "required": false, "description": "New description" },
    "location":    { "type": "string", "required": false, "description": "New location" },
    "attendees":   { "type": "array",  "required": false, "description": "New complete attendee email list (replaces existing list)" },
    "sendUpdates": { "type": "string", "required": false, "description": "'all' | 'externalOnly' | 'none' (default 'all')" },
    "status":      { "type": "string", "required": false, "description": "'confirmed' | 'tentative' | 'cancelled'" },
    "visibility":  { "type": "string", "required": false, "description": "'default' | 'public' | 'private' | 'confidential'" }
  },
  "output": {
    "eventId":    { "type": "string", "description": "Event ID" },
    "calendarId": { "type": "string", "description": "Calendar ID" },
    "title":      { "type": "string", "description": "Updated title" },
    "start":      { "type": "string", "description": "Updated start datetime" },
    "end":        { "type": "string", "description": "Updated end datetime" },
    "htmlLink":   { "type": "string", "description": "URL to open event in Google Calendar web UI" },
    "updated":    { "type": "string", "description": "ISO 8601 timestamp of this update" }
  },
  "tags": ["calendar", "google-calendar", "update", "event", "modify"],
  "credentialRef": "gmail_main",
  "dangerous": false,
  "status": "inactive",
  "version": 1,
  "createdBy": "claude-code",
  "nodeHash": null,
  "usageCount": 0,
  "lastVerified": null,
  "dependsOn": [],
  "allowedCallers": "any"
},

"Calendar.Delete": {
  "n8nId": null,
  "description": "Permanently delete a Google Calendar event",
  "semanticDescription": "Permanently and irreversibly deletes a Google Calendar event by its event ID. By default, cancellation notification emails are sent to all attendees. This action cannot be undone — deleted events cannot be recovered through n8n. Use Calendar.Update with status 'cancelled' instead if you want to cancel the event while keeping it visible in the calendar history. This is a DANGEROUS action — the Nexus Orchestrator will require explicit confirmation before executing it.",
  "input": {
    "eventId":     { "type": "string", "required": true,  "description": "Event ID to delete" },
    "calendarId":  { "type": "string", "required": false, "description": "Calendar containing the event (default: 'primary')" },
    "sendUpdates": { "type": "string", "required": false, "description": "Cancellation notification mode: 'all' (default), 'externalOnly', 'none'" }
  },
  "output": {
    "eventId": { "type": "string", "description": "The event ID that was deleted" },
    "status":  { "type": "string", "description": "'deleted'" }
  },
  "tags": ["calendar", "google-calendar", "delete", "event", "dangerous"],
  "credentialRef": "gmail_main",
  "dangerous": true,
  "status": "inactive",
  "version": 1,
  "createdBy": "claude-code",
  "nodeHash": null,
  "usageCount": 0,
  "lastVerified": null,
  "dependsOn": [],
  "allowedCallers": "any"
},

"Calendar.FindFreeSlot": {
  "n8nId": null,
  "description": "Find available time slots of a specified duration within a search window",
  "semanticDescription": "Queries the Google Calendar free/busy API for a given time window, then computes available time slots of the requested duration that fall within configurable working hours. Returns up to maxSlots candidate slots (default 5) aligned to 15-minute boundaries. Use this before Calendar.Create when you need to find a suitable meeting time — pass one of the returned slot start/end values directly to Calendar.Create. Does NOT book anything — it only reads availability. For simply listing existing events, use Calendar.List instead.",
  "input": {
    "durationMinutes":  { "type": "number",  "required": true,  "description": "Required slot length in minutes (e.g. 30, 60, 90)" },
    "searchStart":      { "type": "string",  "required": false, "description": "ISO 8601 start of search window (default: now)" },
    "searchEnd":        { "type": "string",  "required": false, "description": "ISO 8601 end of search window (default: now + 7 days)" },
    "calendarId":       { "type": "string",  "required": false, "description": "Calendar to check (default: 'primary')" },
    "workdayStartHour": { "type": "number",  "required": false, "description": "Working day start hour in local time (default 9)" },
    "workdayEndHour":   { "type": "number",  "required": false, "description": "Working day end hour in local time (default 17)" },
    "timezone":         { "type": "string",  "required": false, "description": "IANA timezone for workday bounds (default 'US/Central')" },
    "maxSlots":         { "type": "number",  "required": false, "description": "Max free slots to return (default 5)" }
  },
  "output": {
    "slots": {
      "type": "array",
      "description": "Array of { start, end, durationMinutes } representing available time slots"
    },
    "count":    { "type": "number", "description": "Number of free slots found" },
    "searched": { "type": "object", "description": "{ from: ISO, to: ISO } — the window that was searched" }
  },
  "tags": ["calendar", "google-calendar", "availability", "scheduling", "free-slot", "find"],
  "credentialRef": "gmail_main",
  "dangerous": false,
  "status": "inactive",
  "version": 1,
  "createdBy": "claude-code",
  "nodeHash": null,
  "usageCount": 0,
  "lastVerified": null,
  "dependsOn": [],
  "allowedCallers": "any"
}
```

---

## 8. nodeWhitelist Update Required

The `Calendar.ListCalendars` workflow uses an HTTP Request node to call the `calendarList.list` Google API endpoint — the same workaround pattern as `Email.Label`. The `n8n-nodes-base.httpRequest` node is already on the whitelist.

The Google Calendar node itself (`n8n-nodes-base.googleCalendar`) is **not currently on the nodeWhitelist** in `workflow-registry.json`. It must be added before the Builder is allowed to generate Calendar workflows autonomously.

Add this entry to `workflow-registry.json` under `nodeWhitelist`:

```json
"n8n-nodes-base.googleCalendar"
```

The full updated `nodeWhitelist` array:
```json
"nodeWhitelist": [
  "n8n-nodes-base.executeWorkflowTrigger",
  "n8n-nodes-base.set",
  "n8n-nodes-base.code",
  "n8n-nodes-base.httpRequest",
  "n8n-nodes-base.gmail",
  "n8n-nodes-base.googleCalendar",
  "n8n-nodes-base.merge",
  "n8n-nodes-base.if",
  "n8n-nodes-base.switch",
  "n8n-nodes-base.noOp"
]
```

---

## 9. Build Order

Build simple-to-complex. Each workflow builds on knowledge from the previous one.

### Step 1: Calendar.ListCalendars
- Pure HTTP Request — no new Calendar node syntax to learn
- Validates that the `gmail_main` credential has Calendar scope
- Output tells you the exact `calendarId` values to use in subsequent tests
- Build this first to confirm auth works before writing event workflows

### Step 2: Calendar.Get
- Simplest Calendar node operation — single required input (eventId)
- Learn the response shape of the Calendar node (how `start`, `end`, `attendees` are structured)
- Use a known eventId from your calendar for testing (copy from Calendar web UI URL: the `eid` param, or use `calendarList` event URL)

### Step 3: Calendar.List
- `getAll` operation — learn `timeMin`/`timeMax` expressions, `singleEvents`, `q` filter
- Validates that Luxon `$now.plus({ days: 7 })` works correctly in the dateTime field
- Output shape normalization in Format Output is more complex — verify the `start.dateTime` vs `start.date` distinction (all-day events use `date`, not `dateTime`)

### Step 4: Calendar.Create
- First write operation — verify it creates a real event in Google Calendar
- Test `sendUpdates: "none"` first to avoid spamming attendees during development
- Test with a future date well outside working hours to avoid accidental meeting conflicts
- After building, immediately test Calendar.Get on the returned eventId to verify round-trip

### Step 5: Calendar.Update
- Build after Create is verified (you need a real eventId to test against)
- Test the attendees replacement behavior explicitly — create an event with 0 attendees, then update with 1, then update with 2 to confirm replace semantics

### Step 6: Calendar.Delete
- Build last among the simple CRUD operations — requires a test event to delete
- Create a test event via Calendar.Create, capture its eventId, then run Calendar.Delete
- Confirm the delete returns 204 and that the Format Output node correctly pulls the eventId from Validate Input rather than from the (empty) Calendar node output
- Tag this workflow as `dangerous: true` in the registry before activating

### Step 7: Calendar.FindFreeSlot
- Most complex — requires the `availability` operation plus the Code algorithm from Section 6
- Build after all CRUD workflows are verified
- Test with a calendar that has some events in the next 7 days to exercise the busy-block inversion logic
- Edge cases to test: (a) completely free calendar — should return maxSlots slots starting at next workday hour, (b) completely blocked calendar — should return count: 0, (c) search window that ends before workdayEndHour on the last day — verify no overflow

---

## 10. Edge Cases and Gotchas

### All-day events in Calendar.List / Calendar.Get
The Google Calendar API represents all-day events differently from timed events:
- Timed events: `event.start.dateTime = "2026-02-19T14:00:00-06:00"` (ISO 8601 with time)
- All-day events: `event.start.date = "2026-02-19"` (date-only string, no time component)

The Format Output Code node in Calendar.List and Calendar.Get must handle both:
```javascript
const start = e.start?.dateTime || e.start?.date;
const end   = e.end?.dateTime   || e.end?.date;
```
Failing to handle this will cause `null` values for all-day events.

### Recurring events and `singleEvents: false`
When `singleEvents: false` (the API default), recurring event series are returned as a single item with `recurrenceRule` set. When `singleEvents: true`, each occurrence is returned as a separate item. The `eventId` for a recurring instance includes a suffix: `<baseId>_<datestring>`. Calendar.Get on a recurring instance ID works correctly. Calendar.Delete on a recurring instance ID only deletes that occurrence; deleting the base event ID deletes the entire series — document this clearly.

### Calendar node `calendar` field — resourceLocator format
The `calendar` parameter must be a resourceLocator object, not a plain string:
```json
"calendar": { "mode": "id", "value": "primary" }
```
When the calendarId comes from workflow input, use an expression:
```json
"calendar": { "mode": "id", "value": "={{ $json.calendarId }}" }
```
Using a plain string `"primary"` will cause a validation error at the node level.

### Delete returns 204 No Content
The Google Calendar delete API returns HTTP 204 with no response body. The n8n Google Calendar delete operation passes through as an empty item `{}`. The Format Output Set node cannot reference `$json.id` because there is no `$json` — it must pull the eventId from the Validate Input node via `$('Validate Input').first().json.eventId`.

### Update patches, not replaces — except attendees
The Google Calendar update operation in n8n sends a PATCH request for most fields, preserving unset fields. However, the `attendees` array is a full replacement. If the intent is "add one attendee to an existing event", the pattern is:
1. `Calendar.Get` → get current attendees array
2. Append new email to array in a Code node
3. `Calendar.Update` with the merged array

### Timezone in FindFreeSlot and availability
The `availability` operation's `timezone` parameter affects how the API interprets `timeMin`/`timeMax` (though ISO 8601 strings are timezone-unambiguous). More importantly, the Code node's workday clamping uses `Intl.DateTimeFormat` which is available in n8n's JS environment (V8). Verify this works by testing with a timezone boundary (e.g., set `workdayStartHour=9`, `timezone="US/Central"` and confirm slots start at 09:00 CT, not 09:00 UTC).

### `sendUpdates` during development
Default is `"all"` — this sends email invitations to all attendees when an event is created or updated. During development and testing, always set `sendUpdates: "none"` to avoid spamming real people. The Validate Input node can enforce this as a default: `const sendUpdates = $json.sendUpdates || 'all';` — consider changing the default to `"none"` and requiring callers to explicitly opt into sending notifications.

### Google Calendar credential type
In the n8n node JSON, the credential type key is `"googleCalendarOAuth2Api"` (not `"googleOAuth2Api"` or `"gmailOAuth2"`). The credential object ID is the same token (`6IGQz4SKT7kp908J`) that serves Gmail, but the type key in the workflow JSON must match exactly.

### HTTP Request for ListCalendars
For `Calendar.ListCalendars`, the HTTP Request node must use:
```json
{
  "authentication": "predefinedCredentialType",
  "nodeCredentialType": "googleCalendarOAuth2Api"
}
```
Not `"gmailOAuth2"` — even though it is the same physical credential, the node type string must match `googleCalendarOAuth2Api` for the Calendar API host to accept it.

### Pagination in Calendar.List
The Google Calendar `events.list` API paginates via `pageToken`. The n8n `getAll` operation with `returnAll: false` and `limit: N` returns at most N events from the first page. For the standard library use case (limit 10–100), this is fine. Do not implement pagination — callers who need more than 100 events should use a more specific `timeMin`/`timeMax` window.

### Event IDs are opaque base64url strings
Google Calendar event IDs look like `abc123def456_20260219T140000Z` for recurring instances or `abc123def456ghi` for standalone events. They are opaque — do not attempt to parse them. The ID for the primary calendar itself is the user's email address (e.g., `user@gmail.com`) or the literal string `"primary"`.

---

*This document is the implementation specification for the Calendar domain. The Builder Dev agent should read Sections 2, 5, 6, and 9 before starting, refer to Section 10 as gotchas arise, and paste Section 7 entries into the registry after each successful deployment.*
