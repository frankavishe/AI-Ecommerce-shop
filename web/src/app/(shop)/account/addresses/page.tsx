import type { Metadata } from "next";
import { AddressBook } from "./address-book";

export const metadata: Metadata = { title: "Addresses" };

export default function AddressesPage() {
  return <AddressBook />;
}
