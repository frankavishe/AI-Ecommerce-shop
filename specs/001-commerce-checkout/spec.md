# Feature Specification: Commerce Checkout (Cart, Orders, ClickPesa Payments)

**Feature Branch**: `001-commerce-checkout`

**Created**: 2026-10-28

**Status**: Draft

**Input**: User description: "Customers (registered or guest) build a cart, check out with name/phone/address/region, receive a ClickPesa hosted-checkout link, pay with mobile money or card, and the order becomes paid via a verified webhook. Stock is reserved/decremented safely; orders have a status timeline; admins list/filter orders; customers see their orders, and guests look theirs up by order number + phone. Abandoned unpaid orders get reminders and eventually expire."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Guest buys and pays with mobile money (Priority: P1)

A shopper who has no account adds products to a cart, enters their name, phone number, delivery
region and street address, and places the order. They receive a payment link, pay with M-Pesa
(or another supported mobile money wallet or card), and the order is confirmed as paid.

**Why this priority**: This is the core money path. Without it the shop cannot sell anything, and
it is the same path the WhatsApp assistant and the app will reuse later.

**Independent Test**: Using only the shop's API with no account, add an in-stock product to a
cart, check out as a guest, receive a payment link, simulate a successful payment notification,
and confirm the order shows as paid with stock reduced.

**Acceptance Scenarios**:

1. **Given** an anonymous shopper and an active product with stock 10, **When** they add 2 units
   to a new cart, **Then** they receive a cart identifier and the cart shows 2 units at the
   product's current price, a subtotal and the item count.
2. **Given** a guest cart with items, **When** the shopper checks out with name, phone, region and
   street, **Then** an order with a unique human-readable order number is created in
   "awaiting payment" status, totals are computed by the shop (subtotal + delivery fee), the cart
   is emptied, and a payment link is returned.
3. **Given** an order awaiting payment, **When** the payment provider reports a successful payment
   for the full order amount, **Then** the order becomes "paid", the payment is recorded with the
   provider reference, and a timeline entry is added.
4. **Given** a paid order, **When** the same payment notification is delivered again, **Then**
   nothing changes (no duplicate payment records, no duplicate timeline entries).
5. **Given** a checkout request that includes a price or total chosen by the client, **When** the
   order is created, **Then** the client values are ignored and the shop's own prices are used.

---

### User Story 2 - Registered customer's cart and order history (Priority: P2)

A logged-in customer's cart is tied to their account, so it survives across devices and sessions.
They can check out using a saved address, and later see a list of their orders and each order's
status timeline.

**Why this priority**: Returning customers are the main repeat revenue; order history reduces
"where is my order?" support requests.

**Independent Test**: Log in, add to cart, log in again from a second client and see the same cart;
check out with a saved address; list own orders and open one.

**Acceptance Scenarios**:

1. **Given** a logged-in customer, **When** they add items, **Then** the cart belongs to their
   account and is returned on any later request made with their login.
2. **Given** a shopper with a guest cart who then logs in, **When** they present the guest cart
   identifier, **Then** guest items are merged into their account cart (quantities summed, capped
   at available stock).
3. **Given** a logged-in customer with a saved address, **When** they check out choosing that
   address, **Then** the order copies the address details (later edits to the address do not
   change the order).
4. **Given** a customer with orders, **When** they list their orders, **Then** they see only their
   own orders, newest first, with number, date, total and status, and can open an order to see its
   items and timeline.
5. **Given** a guest who placed an order, **When** they look it up with the order number and the
   phone number used at checkout, **Then** they see the order; with a non-matching phone they get
   "not found".

---

### User Story 3 - Admin manages orders (Priority: P3)

A shop admin lists all orders, filters by status, date and payment state, searches by order
number or customer phone, opens an order, and moves it through fulfilment statuses or cancels it.

**Why this priority**: Admins need visibility to fulfil paid orders; delivery assignment (a later
feature) builds on this.

**Independent Test**: As an admin, list and filter orders, change a paid order to "processing",
cancel an unpaid order and see stock returned; as a customer, confirm the admin list is refused.

**Acceptance Scenarios**:

1. **Given** an admin, **When** they list orders filtered by status "paid", **Then** only paid
   orders are returned, newest first, paginated.
2. **Given** a paid order, **When** the admin changes its status to "processing", **Then** the
   status changes and a timeline entry records who changed it and when.
3. **Given** an order awaiting payment, **When** the admin cancels it, **Then** it becomes
   "cancelled" and its reserved stock is returned.
4. **Given** a non-admin user or a guest, **When** they call any admin order action, **Then** the
   request is refused.
5. **Given** an order in a final state (delivered, cancelled, expired), **When** an admin tries an
   invalid transition (e.g. cancelled → paid), **Then** it is rejected with a clear message.

---

### User Story 4 - Abandoned payments: reminder and expiry (Priority: P4)

If a shopper places an order but does not pay, the shop reminds them once, and if the order is
still unpaid after the expiry window it expires automatically and its stock is released.

**Why this priority**: Prevents unpaid orders from locking stock forever and recovers some lost
sales; useful but not required to take the first payment.

**Independent Test**: Create an unpaid order, advance time past the reminder point and then past
the expiry window, run the scheduled jobs, and confirm one reminder was queued and the order
expired with stock restored.

**Acceptance Scenarios**:

1. **Given** an order still awaiting payment after the reminder delay, **When** the scheduled job
   runs, **Then** exactly one reminder is recorded for that order (re-running does not send
   another).
2. **Given** an order still awaiting payment after the expiry window, **When** the scheduled job
   runs, **Then** the order becomes "expired" and its stock is released.
3. **Given** an expired order, **When** a late successful payment notification arrives, **Then**
   the payment is recorded and the order is flagged for admin review instead of silently becoming
   paid (stock may no longer be available).
4. **Given** an order awaiting payment whose payment link failed or was lost, **When** the
   shopper requests a new payment link for it, **Then** a new link is issued for the same order
   and amount.

---

### Edge Cases

- Two shoppers try to buy the last unit at the same moment: exactly one order succeeds; the other
  gets a clear "out of stock" error and no order is created.
- A product in the cart is deactivated or its price changes before checkout: checkout uses the
  current price; inactive products block checkout with a message naming the product.
- Requested quantity is above available stock: adding to the cart or checking out is rejected with
  the available quantity in the message.
- Quantity zero or negative: rejected; setting a cart line to zero removes it.
- Checkout with an empty cart: rejected.
- Phone number not in a valid international format: rejected with a message; local formats like
  `0712345678` are normalised to `+255712345678`.
- Payment notification with an invalid signature/checksum: rejected and not recorded as a payment.
- Payment notification for an unknown order reference: logged and ignored (no error to provider
  loops).
- Payment notification amount lower than the order total: payment recorded as a mismatch, order
  not marked paid, flagged for admin review.
- Payment provider unavailable when creating the link: the order still exists awaiting payment and
  the shopper can retry getting the link.
- A failed payment notification: payment recorded as failed; the order stays awaiting payment so
  the shopper can retry.

## Clarifications

### Session 2026-10-28

- Q: How is the delivery fee set? → A: Admin-managed per-region fee table with a default fee for
  unlisted regions.
- Q: When is stock taken for an order? → A: At order placement; returned on expiry or cancellation.
- Q: How long can an order stay unpaid? → A: 2 hours (reminder at 30 minutes), configurable.

## Requirements *(mandatory)*

### Functional Requirements

**Cart**

- **FR-001**: The system MUST let anonymous shoppers create a cart and identify it later using an
  unguessable cart identifier returned to the client.
- **FR-002**: The system MUST tie a logged-in customer's cart to their account and MUST merge a
  presented guest cart into it on request.
- **FR-003**: Shoppers MUST be able to add a product, change a line quantity, remove a line, view
  the cart and clear it.
- **FR-004**: The cart view MUST show each line's current unit price, line total, the subtotal and
  item count, all computed by the shop.
- **FR-005**: The system MUST reject adding inactive products or quantities above available stock.

**Checkout and orders**

- **FR-006**: Checkout MUST accept either a logged-in customer (optionally choosing a saved
  address) or a guest providing name, phone, region, street and optional district/notes.
- **FR-007**: Checkout MUST compute subtotal, delivery fee and total from shop data, ignoring any
  price, fee or total sent by the client.
- **FR-008**: The delivery fee MUST come from an admin-managed per-region fee table; regions not
  in the table use a configurable default fee. Admins MUST be able to create, edit and deactivate
  regions and fees.
- **FR-009**: Each order MUST get a unique, human-readable order number suitable for reading over
  the phone and use as the payment reference.
- **FR-010**: Each order MUST store a snapshot of items (product, name, unit price, quantity, line
  total) and of the delivery contact and address, unaffected by later catalogue or address edits.
- **FR-011**: Stock MUST be deducted atomically when the order is placed (held while awaiting
  payment) and returned when the order expires or is cancelled before delivery; concurrent
  checkouts MUST NOT oversell.
- **FR-012**: Orders MUST follow defined statuses: awaiting payment → paid → processing → out for
  delivery → delivered; plus cancelled, expired and needs review. Invalid transitions MUST be
  rejected.
- **FR-013**: Every status change MUST add a timeline entry with the new status, time, actor (user,
  system or payment provider) and optional note.
- **FR-014**: Customers MUST be able to list and view only their own orders; guests MUST be able to
  view an order only with its order number plus the matching checkout phone number.

**Payments**

- **FR-015**: On checkout the system MUST create a hosted payment link with the payment provider for
  the order's exact total in TZS, referenced by the order number, and return it to the client.
- **FR-016**: Shoppers MUST be able to request a fresh payment link for an order that is still
  awaiting payment.
- **FR-017**: The system MUST accept payment notifications from the provider, MUST reject those that
  fail authenticity verification, and MUST confirm the payment status with the provider before
  marking an order paid.
- **FR-018**: An order MUST be marked paid only when the confirmed paid amount equals or exceeds the
  order total; otherwise the payment is recorded and the order flagged for admin review.
- **FR-019**: Processing the same payment notification more than once MUST NOT create duplicate
  payments, duplicate timeline entries or repeated side effects.
- **FR-020**: Each payment attempt MUST be stored with provider reference, amount, status, channel
  (e.g. M-Pesa, card) when known, and the raw provider data for audit.

**Admin**

- **FR-021**: Admins MUST be able to list all orders with filters (status, date range, paid/unpaid)
  and search (order number, phone, customer name), and view any order with payments and timeline.
- **FR-022**: Admins MUST be able to move orders through allowed statuses and cancel orders that are
  not yet delivered; cancelling an order that holds stock MUST release it.
- **FR-023**: All admin order actions MUST be refused for non-admin users and guests.

**Abandoned payments**

- **FR-024**: The system MUST record one payment reminder for an order still awaiting payment after
  a reminder delay (delivery of the reminder message over WhatsApp/SMS is out of scope here; the
  reminder is recorded and made available for the notifications feature).
- **FR-025**: Orders still awaiting payment 2 hours after placement (configurable) MUST become
  expired automatically and release their held stock.
- **FR-026**: A successful payment arriving for an expired or cancelled order MUST be recorded and
  the order flagged for admin review rather than marked paid automatically.

### Key Entities

- **Cart**: A shopper's in-progress basket; belongs to a customer account or is identified by a
  guest cart identifier; has lines and timestamps.
- **Cart Line**: A product and quantity in a cart; price is always read live from the product.
- **Order**: A placed purchase with order number, optional customer account, contact name and
  phone, delivery address snapshot and region, subtotal, delivery fee, total (TZS), status and
  timestamps (placed, paid, reminder sent, expires at).
- **Order Item**: Snapshot of a purchased product: product reference, name, unit price, quantity,
  line total.
- **Order Event**: A timeline entry: status, time, actor, note.
- **Payment**: One payment attempt for an order: provider reference, amount, currency, status
  (pending, success, failed, mismatch), channel, payment link, raw provider data.
- **Delivery Region**: A region name (e.g. Dar es Salaam), its delivery fee in TZS and whether it
  is active; plus a shop-wide default fee for unlisted regions.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A guest shopper can go from a filled cart to holding a payment link in under 1 minute
  of form filling, entering at most 5 fields.
- **SC-002**: 100% of successful, verified payment notifications mark the correct order paid
  within 1 minute of receipt.
- **SC-003**: Zero oversold units: under 20 simultaneous checkouts for the last unit of a product,
  exactly one order succeeds.
- **SC-004**: Zero orders marked paid from unverified notifications or with a paid amount lower
  than the order total.
- **SC-005**: Replaying any payment notification 5 times produces the same final state as receiving
  it once.
- **SC-006**: 100% of orders left unpaid past the expiry window are expired and their held stock
  released by the next scheduled run.
- **SC-007**: Admins can find any order by order number or phone in a single search.

## Assumptions

- Currency is TZS only; amounts are whole-shilling values stored with two decimals.
- Product variants (size/colour as separate stock-keeping units) are out of scope; each product has
  one stock count, as in the current catalogue.
- Discounts, coupons, taxes shown separately, and partial refunds are out of scope for this
  feature.
- The payment provider is ClickPesa hosted checkout (mobile money and card); sandbox credentials
  are used for development.
- Sending customer messages (receipts, reminders) over WhatsApp, SMS or push belongs to later
  notifications/WhatsApp features; this feature records the events they will use.
- The web storefront and Android screens are separate features; this feature delivers the shop's
  API and back-office (admin) behaviour only.
- Delivery/rider assignment is a later feature; this feature stops at order statuses an admin can
  set.
- Reminder delay is 30 minutes after placing the order; expiry is 2 hours (both configurable).
- Guest cart identifiers stay valid for 30 days of inactivity.
