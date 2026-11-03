# Feature Specification: Web Storefront, Checkout, Account and Admin

**Feature Branch**: `002-web-storefront`

**Created**: 2026-11-03

**Status**: Draft

**Input**: User description: "Next.js web frontend for the shop, consuming the existing Django API from feature 001. Customers browse the catalog (categories, search, filters, product detail), manage a cart, check out as guests or registered users choosing mobile money (USSD push, network auto-detected or chosen) or card (Stakaba hosted checkout, email required), and track orders (status timeline that updates while awaiting payment, pay again, guest lookup by number + phone). Registered customers log in or register (guest cart merged), manage saved addresses and see order history. Admins manage products (with multi-image upload), categories, orders (filter, detail with payments, status changes) and delivery regions, and see a dashboard with order counts and low-stock products."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Guest buys a product on the website (Priority: P1)

A shopper with no account opens the website, browses or searches the catalog, opens a product, adds it to the cart, adjusts quantities, and checks out. They give their name, phone and delivery address (region, district, street) and see the delivery fee and total. They choose mobile money (their network is guessed from the phone number but they can change it) or card (they give an email). For mobile money they are told to approve the prompt on their phone and land on their order page, which updates by itself when the payment is confirmed. For card they are sent to the payment provider's hosted page.

**Why this priority**: This is the shop's revenue path, and the backend already supports it end to end. Without it, the website has no purpose.

**Independent Test**: With seeded products and delivery regions, a fresh browser can find a product, check out with mobile money, and see the order page change from "awaiting payment" to "paid" once a payment confirmation reaches the backend.

**Acceptance Scenarios**:

1. **Given** active products exist, **When** a shopper opens the home page, **Then** they see categories and recent products with name, image, price in TZS and an out-of-stock marker where relevant.
2. **Given** the catalog page, **When** the shopper searches for a term, picks a category, sets a price range, sorts or changes page, **Then** the list shows only matching products and the URL reflects the filters, so it can be shared or refreshed.
3. **Given** a product page, **When** the shopper adds it to the cart, **Then** the cart count updates, and the cart survives a page reload and browser restart on the same device.
4. **Given** a cart, **When** the shopper changes a quantity beyond the available stock, or the product has become unavailable, **Then** they see a clear message and the cart shows the server's current state.
5. **Given** a non-empty cart, **When** the shopper submits checkout with valid details and mobile money, **Then** an order is created, they are taken to the order page with an "approve the payment prompt on your phone" notice, and the page shows "paid" within seconds of the backend confirming the payment, without a manual refresh.
6. **Given** checkout with card selected and no email, **When** they submit, **Then** they are asked for an email before any order is placed. With an email, they are sent to the hosted card payment page.
7. **Given** the payment could not be started (e.g. provider unavailable or prompt declined), **When** the order page loads, **Then** the shopper sees the reason and a "Pay again" action that lets them choose mobile money or card.
8. **Given** missing or invalid fields (e.g. a phone number that is not a Tanzanian number), **When** they submit, **Then** errors appear next to the relevant fields and nothing is charged.

---

### User Story 2 - Registered customer and order tracking (Priority: P2)

A customer registers or logs in. Any items they added as a guest are kept (merged into their account cart). At checkout they can pick a saved address instead of typing it. They can manage their saved addresses and profile and see their past orders, newest first, opening any of them for details and to pay if still awaiting payment. A guest who has an order number can find that order with the number and their phone.

**Why this priority**: It drives repeat purchases and cuts support requests ("where is my order?"), but it isn't needed for a first sale.

**Independent Test**: Add an item as a guest, register, and confirm the item is still in the cart. Check out with a saved address and confirm the order appears in order history. In a separate browser, find the same order with its number and phone.

**Acceptance Scenarios**:

1. **Given** a guest cart with items, **When** the shopper registers or logs in, **Then** their cart contains the guest items merged with any items already in their account cart.
2. **Given** a logged-in customer with saved addresses, **When** they check out, **Then** they can choose a saved address, and their name and phone are prefilled from their profile.
3. **Given** a logged-in customer, **When** they open their orders, **Then** they see only their own orders, newest first, each with number, date, status and total.
4. **Given** an order number and the phone used at checkout, **When** anyone enters both on the "Track order" page, **Then** the order is shown. A wrong phone gives a generic "not found" message that doesn't reveal whether the number exists.
5. **Given** a logged-in session, **When** the customer logs out, **Then** account pages are no longer reachable and the cart becomes a new guest cart.
6. **Given** wrong login credentials, **When** they submit, **Then** they see a single generic error message.

---

### User Story 3 - Admin runs the shop from the web (Priority: P3)

A shop admin logs in and sees a dashboard with counts of orders awaiting payment, paid and being processed, plus low-stock products. They create and edit products (name, Swahili description, category, price, compare-at price, stock, low-stock threshold, tags, SKU, active flag) and upload several images, then remove or reorder them. They manage categories and delivery regions with their fees. They browse orders with filters (status, paid or not, date range) and search (number, phone, name), open an order to see items, history and payment attempts, and move it to a new status with an optional note.

**Why this priority**: Admins can already use the backend's built-in admin as a stopgap, so this is valuable but not blocking.

**Independent Test**: As an admin, create a product with two images and confirm it appears on the storefront. Find a paid order and move it to processing, and confirm the history shows the change. As a customer, confirm admin pages are unreachable.

**Acceptance Scenarios**:

1. **Given** an admin, **When** they open the dashboard, **Then** they see order counts by status and the low-stock product list.
2. **Given** the product form, **When** the admin saves a product with images, **Then** the product and images appear on the storefront if the product is active, and not if it is inactive.
3. **Given** an order, **When** the admin requests a status change the order rules don't allow, **Then** they see the reason and the order is unchanged.
4. **Given** a customer, guest or rider, **When** they try to open any admin page, **Then** they are sent to log in, or told they have no access, and no admin data is shown.
5. **Given** the orders list, **When** the admin combines filters and search, **Then** only matching orders are listed, newest first, with paging.

---

### Edge Cases

- A product is removed or its stock drops while it sits in the cart: the cart and checkout show the server's message (out of stock / unavailable) and the shopper can fix the cart.
- The cart token cookie is lost or expired: the shopper silently gets a new, empty cart. No error is shown.
- A login session expires mid-use: the site renews it silently if possible. Otherwise the user is asked to log in again and returned to the page they were on.
- The shopper leaves the order page while payment is pending: reopening it from order history or tracking shows the current status.
- Orders that expire unpaid show as expired with no "Pay again" action. Orders confirmed after expiry show "needs review".
- The backend is unreachable: pages show a friendly error with a retry, not a blank page.
- A mobile money amount is below the provider minimum, or a card is chosen without an email: the backend's error message is shown next to the payment choice.
- Prices change between adding to cart and checkout: the order total is whatever the server computes, and the checkout page always shows server-computed values.

## Requirements *(mandatory)*

### Functional Requirements

**Catalog**
- **FR-001**: The site MUST show a home page with active categories and recently added active products.
- **FR-002**: The site MUST let shoppers list products with search, a category filter, a min/max price filter, an in-stock filter, sorting (price, newest, name) and paging, with all of these held in the page address.
- **FR-003**: The site MUST show a product page with all images, name, description (Swahili description when the Swahili language is selected and it exists), category, price, compare-at price (when higher than price) and stock availability, but not exact stock counts.

**Cart and checkout**
- **FR-004**: Shoppers MUST be able to add, change quantity, remove and empty cart items. The cart MUST persist for guests on the same browser and for logged-in customers across devices.
- **FR-005**: All prices, line totals, delivery fees and order totals shown MUST be the values returned by the server. The site MUST NOT compute or send prices.
- **FR-006**: Checkout MUST collect contact name, phone, region (from the active delivery regions, showing each fee), optional district, street and optional notes. Logged-in customers can instead pick a saved address.
- **FR-007**: Checkout MUST offer mobile money (default) with an optional network override (M-Pesa, Airtel Money, Tigo Pesa, HaloPesa), and card, which requires an email.
- **FR-008**: After placing an order, card payments MUST redirect to the hosted payment page. Mobile money MUST show the order page with instructions to approve the prompt on the phone.
- **FR-009**: Field-level and general errors from the server MUST be shown next to the relevant input, or as a page message.

**Orders**
- **FR-010**: The order page MUST show number, status, status history, items, subtotal, delivery fee, total, delivery details and timestamps, and MUST refresh the status automatically at least every 10 seconds while the order awaits payment.
- **FR-011**: When an order awaits payment, the owner (logged-in, or guest who proved ownership with the phone) MUST be able to start a new payment attempt with either method.
- **FR-012**: Anyone MUST be able to look up an order by number plus phone. Failures MUST give one generic message.

**Accounts**
- **FR-013**: Shoppers MUST be able to register, log in and log out. On login or registration, the guest cart MUST be merged into the account cart.
- **FR-014**: Logged-in customers MUST be able to view and edit their profile, add/edit/delete saved addresses, and list their own orders, newest first, with paging.
- **FR-015**: Login credentials and session tokens MUST NOT be readable by page scripts, and sessions MUST renew transparently while valid.

**Admin**
- **FR-016**: Admin pages MUST be reachable only by users with the admin role. Others MUST be redirected to login or shown an access-denied page.
- **FR-017**: Admins MUST be able to list, search, filter (category, active, in stock), create, edit and deactivate products, and upload, reorder, edit alt text for, and delete product images.
- **FR-018**: Admins MUST be able to create, edit and deactivate categories (with Swahili name).
- **FR-019**: Admins MUST be able to list orders with status, paid, date-range filters and search; view order detail including payment attempts and history; and change order status with an optional note, seeing server-side rejections.
- **FR-020**: Admins MUST be able to create, edit and deactivate delivery regions and fees.
- **FR-021**: The admin dashboard MUST show counts of orders awaiting payment, paid and processing, plus the low-stock product list.

**General**
- **FR-022**: All money MUST be displayed in TZS with thousands separators and no fractional digits when the amount is whole.
- **FR-023**: Customer-facing pages MUST be available in English and Swahili via a language switch that persists for the visitor. Admin pages may be English-only.
- **FR-024**: Pages MUST be usable on phone-sized screens (360px wide) as well as desktop.
- **FR-025**: When the backend is unreachable or returns an unexpected error, the site MUST show a friendly message with a retry option.

### Key Entities

- **Product / Category / Product image**: Catalog items shown to shoppers and edited by admins. These are owned by the backend.
- **Cart**: A guest's cart (tied to a browser by a secret token) or a customer's cart, with lines and server-computed subtotal.
- **Order**: Created at checkout, with number, status, history, contact and delivery details, items, totals and the latest payment link.
- **Payment attempt**: Method (mobile money or card), status and reference, visible to admins on the order detail.
- **Delivery region**: Name and fee, chosen at checkout and managed by admins.
- **User session**: The logged-in identity and role (customer, admin, rider) that decides which pages are reachable.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A first-time guest can go from the home page to a placed order in under 3 minutes on a phone.
- **SC-002**: After the backend confirms a payment, the open order page shows "paid" within 10 seconds without user action.
- **SC-003**: Catalog and product pages show content within 2 seconds on a typical 4G connection.
- **SC-004**: 100% of admin pages refuse non-admin users in automated tests.
- **SC-005**: An admin can create a product with images and see it live on the storefront in under 2 minutes.
- **SC-006**: Every customer-facing page has both English and Swahili text, with no untranslated interface strings.

## Assumptions

- The backend API from feature 001 (catalog, cart, checkout, orders, payments, admin orders and regions, accounts) is complete and is the only data source. No backend changes are expected beyond small fixes discovered during integration.
- Payment is confirmed by the backend (webhook). The website only reflects the order status and never decides that an order is paid.
- After a hosted card payment, the provider returns the shopper to the shop's order page if a return address is configured. Otherwise the shopper opens the order via history or tracking.
- Rider management, deliveries, WhatsApp, knowledge-base uploads and reports are out of scope (later features).
- Product content in Swahili comes from the admin-entered Swahili fields. Products without them fall back to English.
- WhatsApp OTP login and phone linking are out of scope. Login is username and password, as the backend supports today. Registration also collects email, name, phone and preferred language.
