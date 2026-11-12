# Contract: WhatsApp account-link API (customer) and web card

All endpoints require an authenticated user (JWT, via the web BFF). They are in the OpenAPI schema
under the tag `whatsapp`.

## GET /api/whatsapp/link/

Response `200`:

```json
{"linked": true, "number": "+255 742 *** 331", "linked_at": "2026-11-12T10:20:00+03:00",
 "business_number": "+255700000000"}
```

When nothing is linked, the response is `{"linked": false, "number": null, "linked_at": null,
"business_number": "…"}`.

## POST /api/whatsapp/link/code/

Request: empty body. Response `201`:

```json
{"code": "LINK-7KQ4XM", "expires_at": "2026-11-12T10:30:00+03:00",
 "wa_link": "https://wa.me/255700000000?text=LINK-7KQ4XM"}
```

- The code has 6 characters from `ABCDEFGHJKLMNPQRSTUVWXYZ23456789`. Only its sha256 is stored.
  It is valid for 10 minutes and works once. A new code replaces any unused code of the same user.
- Throttle: scope `whatsapp_link_code`, 5/hour per user.
- `503 {"detail": "WhatsApp is not configured."}` when `WHATSAPP_BUSINESS_NUMBER` is empty.

## DELETE /api/whatsapp/link/

Unlinks the number and returns `204`. The response is the same when nothing was linked.
`user.whatsapp_verified` becomes false. The contact keeps its history and its WhatsApp-placed
orders.

## In-chat redemption (handled by the processing pipeline, not HTTP)

| Situation | Effect | Reply key |
|---|---|---|
| Valid code, number unlinked or already this user | Link the number, merge the guest cart into the user cart, the conversation acts as the user | `link_ok` |
| Valid code, the user had another number | That number is unlinked, then this one is linked | `link_ok` |
| Number linked to a different user | Nothing changes, the code is marked used | `link_taken` |
| Wrong, expired or used code | An attempt is recorded | `link_failed` |
| More than 5 wrong codes from this number in the last hour | The code isn't checked | `link_failed` |

## Web: "Link WhatsApp" card (account page)

The card is `web/src/app/(shop)/account/whatsapp-link-card.tsx`. It is rendered on
`/account` under `ProfileForm`.

- **Not linked**: the card has a short explanation and a "Get link code" button that calls
  `POST /link/code/`. It then shows the code in a large monospace font, a countdown to
  `expires_at`, an "Open WhatsApp" button (`wa_link`, `target=_blank`) and a "Copy code" button.
  When the code expires, the "Get link code" button comes back.
- **Linked**: the card shows the masked number, the link date and an "Unlink" button. The button
  asks for confirmation inline, not with a browser dialog, and then calls `DELETE`.
- While a code is shown, the card polls `GET /link/` every 5 s for up to 10 minutes, so it flips to
  "Linked" after the shopper sends the code.
- All strings are in `web/src/i18n/sw.ts` and `en.ts` under `account.whatsapp.*`.
- The types are regenerated with `npm run gen:api`.
