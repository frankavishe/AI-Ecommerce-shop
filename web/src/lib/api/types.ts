import type { components } from "./schema";

type S = components["schemas"];
export type Category = S["Category"];
export type Product = S["PublicProduct"];
export type ProductImage = S["ProductImage"];
/** The BFF strips the guest cart token (httpOnly cookie only). */
export type Cart = Omit<S["Cart"], "token">;
export type CartLine = S["CartLine"];
export type Order = S["Order"];
export type OrderSummary = S["OrderSummary"];
export type OrderStatus = S["OrderStatusEnum"];
export type DeliveryRegions = S["DeliveryRegions"];
export type Network = S["MobileMoneyNetworkEnum"];
export type PaymentMethod = S["PaymentMethodEnum"];
export type PaymentStarted = S["PaymentStarted"];
export type Address = S["Address"];
export type User = S["User"];
export type AdminOrder = S["AdminOrder"];
export type AdminOrderSummary = S["AdminOrderSummary"];
export type AdminDeliveryRegion = S["AdminDeliveryRegion"];
export type CheckoutRequest = S["CheckoutRequest"];

/** Checkout and order-with-payment responses add these to Order (orders/views.py order_with_payment). */
export type PlacedOrder = Order & {
  payment_method?: PaymentMethod | null;
  payment_message?: string | null;
  payment_error?: string;
  payment_error_code?: string;
};

export type Paginated<T> = { count: number; next?: string | null; previous?: string | null; results: T[] };

/** Admins get the full ProductSerializer from the same endpoint (catalog/views.py get_serializer_class). */
export type AdminProduct = Product & { stock: number; low_stock_threshold: number; is_active: boolean };
export type AdminOrderEvent = S["AdminOrderEvent"];
export type AdminPayment = S["AdminPayment"];
