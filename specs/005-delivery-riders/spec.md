# Feature Specification: Delivery and Riders

**Feature Branch**: `005-delivery-riders`

**Created**: 2026-11-16

**Status**: Draft

**Input**: User description: "Delivery + riders (Phase 5). Rider registration: admin creates a rider (user role=rider + RiderProfile with vehicle, zone, is_available); the rider receives a WhatsApp welcome with a set-password link. Delivery records: when an order is paid, a Delivery (pending) is created automatically with a status timeline (DeliveryEvent): assigned → picked_up → on_the_way → delivered / failed. Assignment: admin assigns a rider from the web admin dashboard; optional auto-assign picks an available rider in the order's zone. Rider notifications: WhatsApp delivery_assigned template plus an in-app inbox entry (FCM push out of scope — Flutter app is a later phase). Rider AI on WhatsApp: a rider's number is recognized as a rider; rider tools: list my jobs, order/customer details (address, phone) only for orders assigned to them, and update delivery status (e.g. "delivered"); reuses the existing WhatsApp pipeline (004) and AI agent (003) with a rider tool set. Customer updates: every delivery status change notifies the customer on WhatsApp (extending the existing order-status notifications) and shows on the web order page timeline. Admin web: deliveries list, assign action, rider list/management in the Next.js admin. Constraints: Swahili + English, automated tests use mocked models, changes to 003/004 are additive only."

## Context: what already exists

- Orders already move through `paid → processing → out_for_delivery → delivered` (or `cancelled`). Every change is recorded in the order timeline and shown to the customer on the web order page and tracking page. The statuses paid, out for delivery, delivered and cancelled already notify the customer on WhatsApp (004).
- Delivery regions (name + fee) already exist; every order carries the region chosen at checkout, a delivery address and a contact phone.
- A user can already have the rider role with a rider profile (vehicle, zone, availability), and admins can manage rider profiles through the API. There is no rider screen in the web admin yet.
- The WhatsApp channel (004) handles text, voice, photos, staff takeover and STOP/START for customers. The AI assistant (003) answers with a customer tool set.

This feature adds the delivery job between "paid" and "delivered": who carries the order, and where it is on the way. It keeps the order statuses the customer already sees in sync with it.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Admin assigns a rider to a paid order (Priority: P1)

As soon as an order is paid, a delivery job for it appears in the admin's deliveries list as "waiting for a rider". The admin opens it, sees the order's region, address and items, and picks a rider from those who are available (riders covering the order's region shown first). The rider immediately gets a WhatsApp message with the job (order number, region, address, customer name, items count, amount already paid). The admin can reassign the job to another rider or unassign it until it is picked up.

**Why this priority**: Without assignment there is no delivery feature; this alone already replaces the phone calls and paper notes the shop uses today, and lets the admin see which paid orders still have nobody carrying them.

**Independent Test**: Pay an order (sandbox), open the admin deliveries list, assign an available rider, and check that the job shows as assigned and the rider received the WhatsApp job message (fake WhatsApp sender in tests).

**Acceptance Scenarios**:

1. **Given** an order that has just been paid, **When** the admin opens the deliveries list, **Then** a delivery for that order is listed as "waiting for a rider" with its region, address and paid time.
2. **Given** a waiting delivery, **When** the admin assigns an available rider, **Then** the delivery shows as assigned to that rider, the order moves to "processing" if it was still "paid", an entry is added to the delivery timeline, and the rider is sent the job on WhatsApp in the rider's language.
3. **Given** an assigned delivery not yet picked up, **When** the admin reassigns it to another rider, **Then** the new rider gets the job message, the previous rider gets a short "job removed" message, and the timeline records both.
4. **Given** a rider marked unavailable or deactivated, **When** the admin assigns a delivery, **Then** that rider is not offered (or the assignment is refused with a clear message).
5. **Given** the order is cancelled (e.g. refund) while its delivery is waiting or assigned, **When** the cancel is saved, **Then** the delivery is cancelled too and the assigned rider is told the job is off.
6. **Given** a non-admin (customer or rider) user, **When** they try to list deliveries or assign one, **Then** the request is refused.

---

### User Story 2 - Rider handles the job on WhatsApp (Priority: P1)

The rider talks to the shop's WhatsApp number like a customer would, but the shop recognises the number as a rider. In Swahili or English, by text or voice, the rider can ask "kazi zangu ni zipi?" / "my jobs", "address ya order 1042?", "namba ya mteja?", and say "nimechukua mzigo" (picked up), "niko njiani" (on the way), "nimefikisha" (delivered) or "imeshindikana, mteja hapatikani" (failed, with a reason). Each status update is confirmed back to the rider and recorded on the delivery timeline. A rider only ever sees details of deliveries assigned to them.

**Why this priority**: Riders are on motorbikes with basic phones and WhatsApp; this is how the status reaches the shop and the customer without any new app. It is the part that makes delivery visible.

**Independent Test**: With a delivery assigned to a test rider, send simulated rider WhatsApp messages (fake model returning the matching tool calls) and check the job list reply, the details reply, and that "delivered" moves the delivery and the order to delivered.

**Acceptance Scenarios**:

1. **Given** a rider with two active jobs, **When** the rider asks for their jobs, **Then** the reply lists both with order number, region, short address and current status, and nothing else.
2. **Given** a job assigned to the rider, **When** the rider asks for the customer's phone or address of that order, **Then** the reply gives the order's contact phone, contact name and delivery address.
3. **Given** an order that is not assigned to this rider (or does not exist), **When** the rider asks for its details or tries to update it, **Then** the reply says the job was not found among their jobs, and reveals nothing about the order.
4. **Given** an assigned job, **When** the rider says it is picked up / on the way, **Then** the delivery moves to that status and the order becomes "out for delivery".
5. **Given** a job out for delivery, **When** the rider says it is delivered, **Then** the delivery and the order become "delivered", the rider gets a confirmation, and the rider can take a new job.
6. **Given** a job out for delivery, **When** the rider says it failed and why, **Then** the delivery is marked failed with the reason, the admin sees it flagged in the deliveries list for a decision, and the order stays "out for delivery" until the admin acts.
7. **Given** a job still only assigned (not yet picked up), **When** the rider says it is delivered, **Then** the system records picked up and delivered in that order (both on the timeline) and confirms to the rider; a status that goes backwards (e.g. "picked up" after "delivered") is refused with a short explanation.
8. **Given** the rider asks the assistant something unrelated to deliveries (e.g. product prices), **When** the message is answered, **Then** the assistant stays within the rider tools and points the rider to the shop for other matters; it never places orders for the rider through the rider conversation.
9. **Given** a WhatsApp number that belongs to a deactivated rider, **When** it messages the shop, **Then** it is treated as an ordinary customer number (no rider tools).

---

### User Story 3 - Customer follows the delivery (Priority: P2)

The customer sees the delivery progress on the web order page and tracking page (rider assigned, picked up, on the way, delivered), with the rider's first name and vehicle type once assigned. On WhatsApp, the customer gets a message when the order is on the way (with the rider's first name and the rider's phone number so they can coordinate) and when it is delivered, using the existing order-update messages.

**Why this priority**: Customers in Tanzania commonly call to ask "where is my order?"; this answers it without staff effort. It depends on Stories 1–2 producing the statuses.

**Independent Test**: Move a delivery through its statuses and check the order page timeline entries and the WhatsApp messages sent to the order's linked number (fake sender).

**Acceptance Scenarios**:

1. **Given** a delivery assigned to a rider, **When** the customer opens the order page, **Then** the timeline shows "rider assigned" with the rider's first name and vehicle type, and never shows the rider's full name or other riders.
2. **Given** a delivery that goes on the way, **When** the status is saved, **Then** the customer gets the existing "out for delivery" WhatsApp message extended with the rider's first name and phone number, in the customer's language, unless they have opted out (STOP).
3. **Given** a delivery that fails, **When** the status is saved, **Then** the customer is not sent an automatic failure message; the admin decides and the customer hears about the outcome (rescheduled or cancelled) through the existing messages.
4. **Given** the same status update arrives twice (e.g. the rider repeats "delivered"), **When** it is processed, **Then** the customer is notified only once.

---

### User Story 4 - Admin registers and manages riders (Priority: P2)

In the web admin the shop owner adds a rider: name, WhatsApp phone number, vehicle type, the regions they cover, and whether they are available. The rider receives a WhatsApp welcome message (Swahili or English) explaining how to use the shop number for jobs, plus a link to set a password. The admin can edit riders, mark them available/unavailable, and deactivate a rider (who then loses rider access, and whose open jobs must first be reassigned).

**Why this priority**: Riders can be created today through the existing API by a developer, so the MVP (Stories 1–2) can run with seeded riders; a proper admin screen is needed before handing the system to the shop owner.

**Independent Test**: Create a rider in the admin, check the user, profile and welcome message (fake sender); deactivate them and check that their number no longer gets rider tools.

**Acceptance Scenarios**:

1. **Given** the admin rider form, **When** the admin saves a new rider with a valid Tanzanian phone number, **Then** a rider account and profile are created and the welcome message with a single-use set-password link is sent to that number.
2. **Given** a phone number already used by another account, **When** the admin tries to create a rider with it, **Then** the form explains the conflict (and offers to make the existing customer a rider only if they are not an admin).
3. **Given** a rider with open (assigned or on-the-way) jobs, **When** the admin deactivates them, **Then** deactivation is refused until those jobs are reassigned or closed.
4. **Given** a set-password link older than its validity or already used, **When** it is opened, **Then** it is refused and the admin can resend a fresh one.
5. **Given** the welcome message could not be delivered (e.g. number not on WhatsApp), **When** the admin views the rider, **Then** the failure is visible and the admin can resend.

---

### User Story 5 - Admin handles failed deliveries and auto-assignment (Priority: P3)

Failed deliveries are flagged in the deliveries list. For each, the admin either schedules a new attempt (back to waiting / reassigned, keeping the history) or cancels the order through the existing cancel flow. Optionally the admin turns on auto-assign: a newly paid order's delivery is given automatically to the available rider covering its region with the fewest open jobs; if nobody fits, it waits for manual assignment.

**Why this priority**: Failures are rare at the start and can be handled manually; auto-assign only pays off with several riders.

**Independent Test**: Fail a delivery and retry it, then enable auto-assign and pay an order in a region with two available riders; check the less loaded one gets it.

**Acceptance Scenarios**:

1. **Given** a failed delivery, **When** the admin chooses "try again", **Then** a new attempt starts as waiting (or assigned to the chosen rider), the attempt count increases, and the earlier attempt stays in the timeline.
2. **Given** auto-assign is on and two available riders cover the order's region, **When** the order is paid, **Then** the rider with fewer open jobs is assigned (ties: the one idle longest) and receives the job message.
3. **Given** auto-assign is on and no available rider covers the region, **When** the order is paid, **Then** the delivery stays waiting and is highlighted for the admin.
4. **Given** auto-assign is off (the default), **When** an order is paid, **Then** nothing is assigned automatically.

---

### Edge Cases

- An order paid twice by webhook replay must produce exactly one delivery.
- Two admins assign the same delivery at the same moment: one wins, the other sees the current rider.
- The rider updates a job at the same moment the admin reassigns it: the update applies only if the rider is still assigned when it is saved; otherwise the rider is told the job was moved.
- A rider's number is also linked as a customer account (004 account linking): the rider role wins for that number; buying on WhatsApp from that number is not supported in this feature.
- A rider sends a photo or voice note: voice is transcribed (004) and treated like text; photos are acknowledged but not used (proof-of-delivery photo is out of scope unless clarified otherwise).
- An active rider sends STOP: riders cannot opt out of job messages while active, so job messages keep coming and the rider is told to ask the admin to deactivate them.
- Staff takeover (004) works for rider conversations too; while flagged, the assistant does not answer the rider.
- The rider writes outside WhatsApp's 24-hour window: job messages to riders use an approved template, as other proactive messages do.
- An order with pickup or no delivery address: not applicable today — every order has a region and address. Orders created before this feature (already paid or processing) get no delivery automatically; the admin can create one from the order.

## Requirements *(mandatory)*

### Functional Requirements

**Delivery jobs**

- **FR-001**: The system MUST create exactly one open delivery job for each order when it becomes paid, starting as "waiting for a rider".
- **FR-002**: A delivery MUST have one of these statuses: waiting, assigned, picked up, on the way, delivered, failed, cancelled. Allowed moves: waiting→assigned; assigned→waiting (unassign), assigned→assigned (reassign), assigned→picked up; picked up→on the way; picked up or on the way→delivered or failed; failed→waiting or assigned (new attempt); any open status→cancelled.
- **FR-003**: Every delivery status change MUST be recorded on a delivery timeline with time, who made it (admin, rider, system), and an optional note (required for failed).
- **FR-004**: Delivery and order statuses MUST stay consistent: assigning a delivery moves a paid order to processing; picked up or on the way moves the order to out for delivery; delivered moves the order to delivered; cancelling the order cancels its open delivery. Order transitions MUST go through the existing order rules so existing customer notifications fire exactly once.
- **FR-005**: Admins MUST be able to create a delivery job manually for a paid or processing order that has none (orders paid before this feature).

**Assignment**

- **FR-006**: Admins MUST be able to assign, reassign and unassign a delivery until it is picked up. Only active, available riders can be assigned.
- **FR-007**: When choosing a rider, the admin MUST see each rider's covered regions, availability and number of open jobs, with riders covering the order's region listed first.
- **FR-008**: The system MUST offer an auto-assign setting, off by default. When on, a new delivery is assigned to the active, available rider covering the order's region with the fewest open jobs (ties: longest since last assignment); with no match it stays waiting.
- **FR-009**: Concurrent assignment or status updates on the same delivery MUST be serialized so that one wins and the other sees the current state.

**Riders**

- **FR-010**: Admins MUST be able to create, edit, mark available/unavailable and deactivate riders from the web admin: name, WhatsApp phone (unique, Tanzanian format), vehicle type, covered regions (one or more existing delivery regions), preferred language.
- **FR-011**: Creating a rider MUST send a WhatsApp welcome message in the rider's language with a single-use set-password link valid for 72 hours; the admin MUST be able to resend it and see whether it was delivered.
- **FR-012**: A rider with open jobs MUST NOT be deactivated until the jobs are reassigned or closed.
- **FR-013**: Riders MUST be able to mark themselves available/unavailable on WhatsApp ("niko off leo" / "I'm available").

**Rider WhatsApp assistant**

- **FR-014**: Messages from the WhatsApp number of an active rider MUST be handled with a rider tool set instead of the customer tool set; numbers of deactivated riders are treated as customers.
- **FR-015**: Rider tools MUST be: list my open jobs; job details (order number, contact name, contact phone, address, region, item names and quantities, amount already paid); update status (picked up, on the way, delivered, failed + reason); set my availability.
- **FR-016**: Every rider tool MUST check on the server that the delivery is currently assigned to the requesting rider; anything else MUST be answered as "not found among your jobs" without revealing whether the order exists.
- **FR-017**: Status updates from the rider assistant MUST be confirmed back to the rider in plain words, and MUST be idempotent (repeating "delivered" changes nothing and notifies no one again).
- **FR-018**: The rider assistant MUST support Swahili and English, text and voice notes, and keep the existing per-number ordering, staff takeover and audit of conversations from 004.

**Notifications**

- **FR-019**: A rider MUST be messaged on WhatsApp when a job is assigned to them, removed from them, or cancelled, using an approved template when outside the 24-hour window.
- **FR-020**: Each assignment, removal and cancellation MUST also be stored as a rider inbox entry (read/unread) for the future rider app; this feature exposes the inbox through the API only.
- **FR-021**: The customer's existing "out for delivery" WhatsApp message MUST include the rider's first name and phone number when a rider is assigned; customer opt-out (STOP) is respected. No other new customer WhatsApp messages are added.
- **FR-022**: The customer order page and tracking page MUST show delivery progress (rider assigned with first name and vehicle type, picked up, on the way, delivered) in the customer's language, without exposing other rider data.

**Admin web**

- **FR-023**: The web admin MUST have a deliveries list filterable by status, region and rider, with failed and long-waiting deliveries highlighted, and a delivery detail view with the timeline and the assign/reassign/unassign, retry and cancel actions.
- **FR-024**: The web admin MUST have a riders list and rider form (create/edit/availability/deactivate/resend welcome).

**Access and safety**

- **FR-025**: All delivery and rider management actions MUST be admin-only, enforced on the server; riders reach only their own jobs; customers see only their own order's delivery progress.
- **FR-026**: Text from riders and order data passed to the assistant MUST be treated as data, never as instructions; the assistant MUST NOT change anything a tool did not confirm.

### Key Entities

- **Delivery**: The job of carrying one order to its address. Order, current rider (optional), status, attempt number, failure reason, times of assignment/pickup/delivery. One open delivery per order at a time.
- **Delivery event**: One entry on a delivery's timeline: status, time, actor type and actor, note.
- **Rider profile** (existing, extended): User with the rider role; vehicle, covered regions, availability, active flag, preferred language, last assignment time.
- **Rider inbox entry**: A message for a rider (job assigned, removed, cancelled) with read state, for the future rider app.
- **Set-password link**: Single-use, time-limited link sent to a new rider.
- **Delivery settings**: Shop-wide auto-assign on/off.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every paid order has a delivery job visible to the admin within 1 minute of payment, with zero duplicates across webhook replays.
- **SC-002**: An admin can assign a rider to a waiting delivery in under 30 seconds from opening the deliveries list.
- **SC-003**: A rider receives the job message within 1 minute of assignment.
- **SC-004**: In a scripted evaluation of at least 30 rider messages (Swahili and English, text and voice), at least 90% of status updates and job questions lead to the correct action or answer on the production model.
- **SC-005**: Zero cases, across automated tests of all rider tools, where a rider can read or change a delivery not assigned to them.
- **SC-006**: The customer sees each delivery status on the order page within 1 minute of the change, and receives the "on the way" and "delivered" WhatsApp messages exactly once per delivery.
- **SC-007**: Customer "where is my order?" questions to staff drop noticeably after launch (tracked qualitatively by the shop owner over the first month).

## Assumptions

- Zones are the existing delivery regions; a rider can cover several regions. The free-text zone on the rider profile is replaced by region links.
- Payment is always taken online before delivery (Stakaba); cash on delivery is out of scope.
- Riders use WhatsApp only in this feature. The set-password link exists so the future rider app (Phase 7) and the web can be used later; no rider web screens are built now.
- FCM push notifications, live rider location/GPS tracking, ETAs, delivery fee changes, route optimisation and rider payouts are out of scope.
- Proof of delivery is the rider's word ("delivered") recorded with time and rider identity; photos or customer confirmation codes are out of scope.
- Admin cancel and refund flows stay as they are (001/002); this feature only reacts to a cancelled order.
- The production model (GPU) is used for SC-004; local CPU runs may be flaky, as in 003/004.
- Rider job templates (assigned, removed, cancelled, welcome) need Meta approval before going live; tests use the fake sender.
- Changes to 003 (agent) and 004 (WhatsApp pipeline) are additive: a rider tool set and routing by number, no changes to customer behaviour.
