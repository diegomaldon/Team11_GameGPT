"use client";

import { MockProvider } from "@/lib/mock/store";

export function Providers({ children }: { children: React.ReactNode }) {
  return <MockProvider>{children}</MockProvider>;
}
