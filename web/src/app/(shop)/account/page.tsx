import type { Metadata } from "next";
import { ProfileForm } from "./profile-form";

export const metadata: Metadata = { title: "My account" };

export default function AccountPage() {
  return <ProfileForm />;
}
