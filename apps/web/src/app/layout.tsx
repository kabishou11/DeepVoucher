import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "凭证自动录入工作台",
  description: "AI-assisted voucher entry with visible workflow and human review.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
