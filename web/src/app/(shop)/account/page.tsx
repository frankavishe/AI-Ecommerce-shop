import type { Metadata } from "next";
import { ProfileForm } from "./profile-form";
import { WhatsAppLinkCard } from "./whatsapp-link-card";

export const metadata: Metadata = { title: "My account" };

export default function AccountPage() {
  return (
    <>
      <ProfileForm />
      <WhatsAppLinkCard />
    </>
  );
}
