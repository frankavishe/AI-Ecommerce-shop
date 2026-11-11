# Feature Specification: WhatsApp Shopping Channel

**Feature Branch**: `004-whatsapp-channel`

**Created**: 2026-11-11

**Status**: Draft

**Input**: User description: "WhatsApp channel (004): let shoppers use the existing AI shopping assistant (003) through the Meta WhatsApp Cloud API. Inbound webhook must verify X-Hub-Signature-256 and the GET verify-token handshake, and must ignore duplicate message IDs (idempotent). A WhatsApp phone number maps to a guest or existing customer conversation and reuses the 003 assistant service unchanged. Supported inbound messages: text, images (routed to search-by-photo), and voice notes (transcribed by a self-hosted whisper model, then sent to the assistant as text; this is the voice work deferred from 003). Outbound: text replies, product images, and the Stakaba payment link. Respect WhatsApp's 24-hour customer-service window and use approved template messages outside it (e.g. order paid/shipped notifications). Human handoff hands the conversation to staff, reusing 003 handoff. Messages are processed asynchronously (Celery), with per-number rate limits and a fallback reply when the model service is down. Swahili-first, Tanzania. Automated tests mock the Graph API and whisper; an opt-in sandbox marker allows real calls, like the Stakaba sandbox tests."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Shopper chats with the shop on WhatsApp (Priority: P1)

A shopper sends a text message to the shop's WhatsApp number, for example "nataka viatu
vyekundu chini ya 50,000". The shop's assistant replies on WhatsApp in the same language, with
the same answers the 003 assistant would give: real products, real prices, and follow-up
questions that remember the conversation. Products the assistant recommends arrive with their
photo.

**Why this priority**: WhatsApp is where Tanzanian shoppers already are. Without this story,
nothing else in the feature is reachable.

**Independent Test**: send a simulated, correctly signed text message from a new number. Check
that a conversation is created for that number, the assistant runs once, and one reply is sent
back to that number with real product names and prices.

**Acceptance Scenarios**:

1. **Given** a number that has never messaged the shop, **When** it sends "nataka viatu
   vyekundu", **Then** a WhatsApp conversation is started for that number and the shopper gets a
   Swahili reply that lists matching active products with their stored prices.
2. **Given** an ongoing conversation, **When** the shopper writes "nionyeshe ya pili", **Then**
   the assistant uses the earlier messages and shows the second product's details.
3. **Given** a reply that refers to products with photos, **When** it is delivered, **Then**
   the shopper also receives the main photo of each product (at most 3), each with its name and
   price.
4. **Given** a message whose signature is missing or wrong, **When** it arrives, **Then** it is
   rejected and nothing is stored, processed or sent.
5. **Given** the same message delivered twice (a provider retry), **When** both copies arrive,
   **Then** the assistant runs once and the shopper gets one reply.
6. **Given** a shopper who sends several messages quickly, **When** they are processed, **Then**
   they are answered in the order sent, and the rate limit sends a polite "please slow down" note
   instead of running the assistant on every message of a flood.
7. **Given** the model service is down, **When** a shopper writes, **Then** they get a short
   apology in their language and the message is saved.

---

### User Story 2 - Shopper orders and pays from WhatsApp (Priority: P2)

From the WhatsApp chat, the shopper adds items to the cart, gives delivery details and asks to
pay. They receive the payment link as a WhatsApp message. They can ask about an order's status
any time. Their WhatsApp number counts as proof of identity for orders placed from it.

**Why this priority**: it turns WhatsApp chats into sales. It depends on Story 1.

**Independent Test**: through simulated WhatsApp messages only, add a product, give details,
confirm, and check that the payment link sent on WhatsApp belongs to an order whose lines and
total match the database. Then ask "oda yangu iko wapi?" and check that the status of that
order is returned without asking for the phone again.

**Acceptance Scenarios**:

1. **Given** a WhatsApp guest with items in the cart who asks to pay, **When** the assistant
   collects details, **Then** the WhatsApp number is offered as the contact phone, and the shopper
   only needs to give name, region and street.
2. **Given** confirmed details, **When** the order is created, **Then** the shopper receives the
   payment link on WhatsApp, and the total in the message equals the order's stored total.
3. **Given** an order placed from a WhatsApp number, **When** the same number asks for its
   status, **Then** the status is given without asking for the order number and phone again.
4. **Given** an order placed from another number, **When** this number asks about it, **Then**
   the order number and the matching phone are still required (the 003 rule).
5. **Given** a number that matches a registered customer's phone but was never linked, **When**
   the shopper asks "where is my order?", **Then** only orders placed from this WhatsApp number
   are shown, not the account's other orders.
6. **Given** a logged-in customer who got a link code from the shop, **When** they send that code
   from their WhatsApp number within 10 minutes, **Then** the number is linked to their account
   and they can see their account orders and use saved addresses in the WhatsApp chat.
7. **Given** a wrong, expired or already-used code, **When** it is sent, **Then** nothing is
   linked and the shopper is told the code didn't work.

---

### User Story 3 - Shopper sends a photo or a voice note (Priority: P3)

Instead of typing, the shopper sends a photo of a product ("hii mnayo?") or a voice note in
Swahili or English. Photos go to the photo search from 003. Voice notes are turned into text
and answered as if typed. The shopper can see what the assistant heard.

**Why this priority**: many shoppers prefer photos and voice to typing on WhatsApp. Text alone
still covers the core flows.

**Independent Test**: send a simulated photo message of a catalog product and check that it
appears in the reply. Send a simulated Swahili voice note whose transcript asks for a product,
and check that the reply answers it.

**Acceptance Scenarios**:

1. **Given** indexed product images, **When** a shopper sends a photo with or without a caption,
   **Then** the reply suggests visually similar products, as in 003 Story 4.
2. **Given** a voice note asking "mna simu za Samsung?", **When** it is processed, **Then** the
   reply answers the question in Swahili and starts with a short line showing what was heard.
3. **Given** a voice note that is too long (over 2 minutes), unclear, or fails to transcribe,
   **When** it is processed, **Then** the shopper is asked in their language to type the
   message or send a shorter one.
4. **Given** an unsupported message type (video, document, sticker, location, contact),
   **When** it arrives, **Then** the shopper is told which kinds of messages are supported, and
   the assistant does not run.
5. **Given** an image larger than 10 MB or of an unsupported type, **When** it arrives, **Then**
   it is rejected with a clear message.

---

### User Story 4 - Staff take over a WhatsApp conversation (Priority: P4)

When a shopper asks for a person, or the assistant can't help, the conversation is flagged for
staff (the 003 handoff). An admin sees the flagged WhatsApp conversations with their history,
replies to the shopper from the shop's admin tools, and the reply is sent on WhatsApp. When
done, the admin hands the conversation back to the assistant.

**Why this priority**: shoppers need a person for complaints and unusual requests. It can wait
until the main buying flow works.

**Independent Test**: flag a WhatsApp conversation, send a staff reply as an admin, check that
it reaches the shopper's number and is stored in the history, and check that the assistant does
not answer while the conversation is flagged.

**Acceptance Scenarios**:

1. **Given** a flagged WhatsApp conversation, **When** the shopper writes more messages,
   **Then** the messages are saved and shown to staff, and the assistant does not reply.
2. **Given** an admin viewing a flagged conversation, **When** they send a reply, **Then** the
   shopper receives it on WhatsApp and it appears in the history as a staff message.
3. **Given** the shopper's last message is more than 24 hours old, **When** an admin tries to
   send a free-text reply, **Then** the system blocks it, explains why, and offers the approved
   "we're getting back to you" template instead.
4. **Given** a non-admin, **When** they try to list conversations or send a staff reply,
   **Then** access is denied.
5. **Given** an admin releases the conversation, **When** the shopper writes again, **Then** the
   assistant answers again.

---

### User Story 5 - Shopper gets order updates on WhatsApp (Priority: P5)

A shopper who ordered from WhatsApp gets WhatsApp updates when their order is paid, goes out for
delivery, is delivered, or is cancelled or expires unpaid. Updates are sent even when the shopper
has not written for more than 24 hours, using messages pre-approved by WhatsApp.

**Why this priority**: it builds trust and cuts "where is my order?" questions. The buying flow
works without it.

**Independent Test**: place an order from a simulated WhatsApp number, mark it paid through the
payment flow, then move it to "out for delivery". Check that one update is sent for each change,
and none is sent twice when the same change is replayed.

**Acceptance Scenarios**:

1. **Given** an order placed from WhatsApp, **When** its payment is confirmed, **Then** the
   shopper receives one "payment received" message with the order number and total.
2. **Given** the shopper's last message is more than 24 hours old, **When** the order goes out
   for delivery, **Then** the update is sent as an approved template in the shopper's language.
3. **Given** a payment notification replayed 5 times, **When** it is processed, **Then** the
   shopper receives exactly one "payment received" message.
4. **Given** an order placed on the website, **When** its status changes, **Then** no WhatsApp
   message is sent (the opt-in rule in FR-021).
5. **Given** sending an update fails at the provider, **When** it is retried, **Then** it is
   retried a few times with increasing delays, and a final failure is recorded for staff. The
   order's state is not affected.

---

### Edge Cases

- WhatsApp sends status callbacks (sent, delivered, read, failed) for the shop's own outgoing
  messages. These are recorded and never sent to the assistant.
- A message arrives for a different business phone number than the shop's: it is ignored.
- Messages arrive out of order or after a delay: they are handled by the time the shopper sent
  them. Messages older than 24 hours on arrival are saved but not answered by the assistant.
- An assistant turn takes longer than the time limit: the shopper gets the fallback message, and
  a late answer is not sent afterwards.
- The shopper blocks the shop or the number can't receive messages: the send failure is recorded,
  and no further retries are made for that message.
- The provider's media download fails or the link expires: the shopper is asked to send the photo
  or voice note again.
- A reply is longer than WhatsApp's per-message limit: it is split into several messages in order,
  without cutting words, prices or links in half.
- The shopper sends "STOP" (or "acha"): they stop receiving order updates (FR-021). Replies to
  their own messages continue.
- The same shopper uses both the website and WhatsApp: the two are separate conversations and
  separate carts, unless the account-linking rule (FR-008) joins them.
- WhatsApp access settings are missing or wrong (token expired): incoming messages are saved, sends
  fail with a clear error in the logs, and the web shop is not affected.

## Requirements *(mandatory)*

### Functional Requirements

**Receiving messages**

- **FR-001**: The system MUST complete WhatsApp's subscription handshake only when the
  configured verification secret matches, and refuse it otherwise.
- **FR-002**: Every incoming notification MUST be checked against WhatsApp's signature using the
  shop's app secret. Unsigned or badly signed notifications MUST be rejected without being stored
  or processed.
- **FR-003**: The system MUST acknowledge valid notifications quickly and do all slow work
  (downloading media, transcription, the assistant, sending) in the background.
- **FR-004**: Each WhatsApp message MUST be processed at most once, based on WhatsApp's message
  ID. Replays and duplicate deliveries MUST NOT trigger a second assistant run or reply.
- **FR-005**: Messages from one number MUST be handled one at a time, in the order sent.
- **FR-006**: Supported inbound types are text, image (with optional caption) and voice/audio.
  Other types MUST get a short "here's what I can handle" reply in the shopper's language. Button
  and list replies, if used, MUST be treated as text.

**Shoppers and conversations**

- **FR-007**: Each WhatsApp number (stored in E.164 format) MUST map to one active WhatsApp
  conversation with its own cart, reusing the 003 conversation, cart and assistant without
  changing their rules.
- **FR-008**: A WhatsApp conversation MUST start as a guest conversation, even when the number
  matches a registered customer's phone. A logged-in customer MAY link their account by getting a
  short one-time link code from the shop (valid 10 minutes, single use) and sending it from their
  WhatsApp number. On a match, the number is linked to that account and marked as WhatsApp-verified,
  and from then on the conversation acts as that customer (their account orders and saved
  addresses). A wrong or expired code changes nothing, and repeated wrong codes from one number
  are rate-limited. A customer can unlink their number. Linking a number already linked to another
  account MUST be refused.
- **FR-009**: The WhatsApp number MUST count as a verified phone for that conversation. A guest
  on WhatsApp can see orders placed from the same number without giving the phone again, and is
  offered that number as the delivery contact.
- **FR-010**: All 003 permission rules still apply. A WhatsApp shopper MUST NOT reach another
  number's conversation, cart or orders.

**Voice and photos**

- **FR-011**: Voice notes up to 2 minutes MUST be turned into text by a self-hosted speech model
  (Swahili and English), then answered as if typed. The reply MUST begin with a short line
  showing what was heard. Longer, empty or failed voice notes MUST get a "please type or send a
  shorter note" reply.
- **FR-012**: Shopper photos MUST go to the 003 photo search, with the same type and size
  limits (JPEG, PNG, WebP; 10 MB).
- **FR-013**: The voice transcript MUST be stored with the message. Voice audio and photos follow
  the 003 retention rule (deleted after 30 days).

**Sending messages**

- **FR-014**: Assistant replies MUST be sent as WhatsApp text, split into several messages when
  over the per-message limit without breaking words, prices or links.
- **FR-015**: When a reply refers to products, the system MUST also send each product's main
  photo with its name and server price (at most 3 per reply).
- **FR-016**: Payment links MUST be sent as WhatsApp messages, with the order number and server
  total.
- **FR-017**: Free-form messages (assistant replies and staff replies) MUST only be sent within
  24 hours of the shopper's last message. Outside that window, only approved template messages
  may be sent.
- **FR-018**: Every outgoing message MUST be recorded with its delivery status (sent, delivered,
  read, failed) as reported by WhatsApp. Temporary send failures MUST be retried a few times with
  increasing delays. Permanent failures MUST NOT be retried.

**Rate limits and failures**

- **FR-019**: The system MUST limit how many messages per number the assistant processes per
  minute and per day. A shopper over the limit gets one polite "please slow down" note per
  window, not one per message.
- **FR-020**: When the model service, speech model or image service is unavailable or too slow,
  the shopper MUST get a short apology in their language, the incoming message MUST be saved, and
  no cart or order change may be half-done (the 003 rule).

**Order updates**

- **FR-021**: For orders placed from a WhatsApp conversation, the shopper MUST receive one
  WhatsApp update when the order is paid, out for delivery, delivered, cancelled or expired.
  Each update is sent once per change, even if the change is replayed. Orders placed elsewhere
  get no WhatsApp updates in this feature. A shopper who replies "STOP" or "acha" stops getting
  updates.
- **FR-022**: Update messages MUST use templates approved by WhatsApp, in Swahili or English
  following the conversation's language, and MUST show order numbers and totals from the database.

**Staff tools**

- **FR-023**: Admins MUST be able to list WhatsApp conversations (filtered by "needs a human"),
  read a conversation's history including transcripts and photos, send a staff reply, and release
  the conversation back to the assistant. Non-admins MUST be denied.
- **FR-024**: A staff reply outside the 24-hour window MUST be blocked with a clear reason, and
  the admin MUST be offered the approved "we'll get back to you" template instead.

**Testing and configuration**

- **FR-025**: WhatsApp access settings (business number ID, access token, app secret,
  verification secret, template names) and the speech-model endpoint MUST come from configuration
  only. Automated tests MUST NOT call WhatsApp or the speech model. Real calls MUST only run in an
  opt-in sandbox test group.

### Key Entities

- **WhatsApp Contact**: a WhatsApp number (E.164) with its profile name, linked customer account
  (if any), language, "updates allowed" flag, and the time of the shopper's last message (for the
  24-hour window).
- **WhatsApp Inbound Message**: one message received from WhatsApp: its WhatsApp message ID
  (unique), type, sent time, text or caption, media reference, transcript, processing status, and
  the chat message it became.
- **WhatsApp Outbound Message**: one message the shop sent: its type (text, image, template),
  what triggered it (assistant reply, staff reply, order update), WhatsApp message ID, delivery
  status with times, attempts and failure reason.
- **WhatsApp Link Code**: a short one-time code issued to a logged-in customer, with its expiry
  and whether it was used, so they can link their WhatsApp number to their account.
- **Order Notification**: a record that the update for a given order and status change was sent,
  so replays don't send it twice.
- Reused from 003: **Conversation** (channel = WhatsApp) and **Chat Message** (now also with a
  staff role and a transcript).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of notifications with a missing or wrong signature are rejected, and none of
  them causes a stored message, an assistant run or a sent message.
- **SC-002**: Delivering the same WhatsApp message 5 times produces exactly one assistant run and
  one reply. Replaying the same order change 5 times produces exactly one order update.
- **SC-003**: On production model hardware, 90% of text messages get a WhatsApp reply within 10
  seconds of arrival, and 90% of voice notes under 30 seconds within 15 seconds.
- **SC-004**: A shopper can go from a first product question to receiving a payment link entirely
  on WhatsApp in 6 messages or fewer for a single-product order.
- **SC-005**: In 100% of tested replies and updates, prices, totals and order numbers sent on
  WhatsApp match the database exactly.
- **SC-006**: Zero free-form messages are sent outside the 24-hour window in tests. Every such
  attempt is blocked or replaced by an approved template.
- **SC-007**: On a labelled set of at least 20 Swahili and English voice notes about the shop, the
  product the shopper asked for appears in the reply for at least 80% of them (on production
  hardware).
- **SC-008**: When the model service is unavailable, 100% of incoming text messages still get a
  fallback reply on WhatsApp within 30 seconds.

## Assumptions

- The shop has a Meta WhatsApp Business account with a business phone number and a permanent
  access token. Template messages (order updates in Swahili and English, plus "we'll get back to
  you") are submitted to Meta and approved outside this feature. Development uses Meta's test
  number and the opt-in sandbox tests.
- The 003 assistant, its tools, handoff, retention rules and limits are reused unchanged. The
  development model's known gaps (unreliable order confirmation and photo-search actions) are
  judged on production models, not fixed here.
- Development runs the speech model on CPU behind the same configurable endpoint as production;
  the CPU setup only needs to work correctly, not fast.
- Staff tools in this feature are admin-only API actions plus the existing back-office admin.
  A dedicated staff inbox screen in the web app is a later feature.
- Marketing broadcasts, catalog/commerce features inside WhatsApp, interactive buttons for
  checkout, group chats, and replying with voice are out of scope.
- One shop business number. Multiple numbers or WhatsApp accounts are out of scope.
- WhatsApp conversation pricing from Meta is accepted as an operating cost. Rate limits keep it
  bounded.
