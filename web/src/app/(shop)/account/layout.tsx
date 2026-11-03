import { AccountNav } from "./account-nav";

export default function AccountLayout({ children }: LayoutProps<"/account">) {
  return (
    <div className="flex flex-col gap-6">
      <AccountNav />
      {children}
    </div>
  );
}
