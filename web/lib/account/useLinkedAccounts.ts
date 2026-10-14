"use client";

// Loads the signed-in user's linked accounts from platform_accounts. REQ003 · TM11-52.
// Every load reads the database, so a refresh shows what is stored, never a cached guess.

import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import {
  loadLinkedAccounts,
  type AccountsDb,
  type LinkedAccount,
} from "@/lib/account/linkedAccounts";

export type LinkedAccountsState =
  | { status: "loading" }
  | { status: "ready"; accounts: LinkedAccount[] }
  | { status: "error"; message: string };

// supabase-js's query builder is a superset of AccountsDb; its generics don't line up with
// the narrow slice, hence the cast. Tests replace "@/lib/supabase" with an in-memory fake.
export const accountsDb = supabase as unknown as AccountsDb;

export function useLinkedAccounts(userId: string | null): {
  state: LinkedAccountsState;
  reload: () => void;
} {
  const [state, setState] = useState<LinkedAccountsState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!userId) {
      return;
    }
    let live = true;
    loadLinkedAccounts(accountsDb).then(
      (accounts) => live && setState({ status: "ready", accounts }),
      (err: Error) => live && setState({ status: "error", message: err.message }),
    );
    return () => {
      live = false;
    };
  }, [userId, attempt]);

  const reload = useCallback(() => setAttempt((n) => n + 1), []);
  return { state, reload };
}
