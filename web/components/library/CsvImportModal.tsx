"use client";

// Import a library from a CSV file, with a review step (TM11-55, REQ004).
//
// Three steps: pick a platform and a file, review what each row matched and
// untick anything wrong, then add. Nothing is saved before "Add games", and the
// server checks the same file again on commit (api/services/csv_import.py).

import { useState } from "react";
import { ApiError, commitCsvImport, previewCsvImport } from "@/lib/api/client";
import type {
  CsvCommitResponse,
  CsvPlatform,
  CsvPreviewResponse,
  CsvRowResult,
  CsvRowStatus,
} from "@/lib/api/types";
import { CsvFileProblem, readCsvFile } from "@/lib/library/csvFile";
import { Button, Field, Modal, Select, cx } from "@/components/ui";

type Step =
  | { name: "choose" }
  | { name: "review"; csvText: string; preview: CsvPreviewResponse }
  | { name: "done"; result: CsvCommitResponse };

const PLATFORM_OPTIONS: { value: CsvPlatform; label: string }[] = [
  { value: "epic", label: "Epic Games" },
  { value: "xbox", label: "Xbox" },
  { value: "steam", label: "Steam" },
];

const STATUS_LABEL: Record<CsvRowStatus, string> = {
  matched: "Will be added",
  already_owned: "Already owned",
  duplicate: "Duplicate",
  ambiguous: "Needs review",
  unmatched: "No match",
  invalid: "Can't import",
};

/** Rows the user can untick. The rest are skipped whatever they choose. */
const SELECTABLE: CsvRowStatus[] = ["matched", "ambiguous", "unmatched"];

const FALLBACK_ERROR = "Something went wrong. Nothing was changed.";

export function CsvImportModal({
  open,
  onClose,
  onImported,
}: {
  open: boolean;
  onClose: () => void;
  onImported: (result: CsvCommitResponse) => void;
}) {
  const [step, setStep] = useState<Step>({ name: "choose" });
  const [platform, setPlatform] = useState<CsvPlatform>("epic");
  const [file, setFile] = useState<File | null>(null);
  const [excludedRows, setExcludedRows] = useState<Set<number>>(new Set());
  const [error, setError] = useState<string | null>(null);
  const [isBusy, setIsBusy] = useState(false);

  function close() {
    setStep({ name: "choose" });
    setFile(null);
    setExcludedRows(new Set());
    setError(null);
    onClose();
  }

  async function run(action: () => Promise<void>) {
    setIsBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setIsBusy(false);
    }
  }

  function review() {
    if (!file) {
      setError("Choose a CSV file first.");
      return;
    }
    void run(async () => {
      const csvText = await readCsvFile(file);
      const preview = await previewCsvImport(platform, csvText);
      setExcludedRows(new Set());
      setStep({ name: "review", csvText, preview });
    });
  }

  function commit(csvText: string) {
    void run(async () => {
      const result = await commitCsvImport(platform, csvText, [...excludedRows]);
      setStep({ name: "done", result });
      onImported(result);
    });
  }

  function toggleRow(rowNumber: number) {
    setExcludedRows((current) => {
      const next = new Set(current);
      if (next.has(rowNumber)) {
        next.delete(rowNumber);
      } else {
        next.add(rowNumber);
      }
      return next;
    });
  }

  return (
    <Modal
      open={open}
      onClose={close}
      title="Import from a CSV file"
      footer={
        <Footer
          step={step}
          excludedRows={excludedRows}
          isBusy={isBusy}
          onCancel={close}
          onBack={() => setStep({ name: "choose" })}
          onReview={review}
          onCommit={commit}
        />
      }
    >
      {error && (
        <p role="alert" className="mb-3 rounded-lg bg-rose-50 px-3 py-2 text-[13px] text-rose-700">
          {error}
        </p>
      )}
      {step.name === "choose" && (
        <ChooseFile platform={platform} onPlatform={setPlatform} onFile={setFile} />
      )}
      {step.name === "review" && (
        <ReviewRows preview={step.preview} excludedRows={excludedRows} onToggle={toggleRow} />
      )}
      {step.name === "done" && <DoneSummary result={step.result} />}
    </Modal>
  );
}

function ChooseFile({
  platform,
  onPlatform,
  onFile,
}: {
  platform: CsvPlatform;
  onPlatform: (platform: CsvPlatform) => void;
  onFile: (file: File | null) => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <p className="text-[13px] text-[var(--ink-soft)]">
        One game per row, with a header row that has a <code>title</code> column. A{" "}
        <code>steam_appid</code> column is optional. Up to 2,000 games and 1 MB.
      </p>
      <Field label="Platform" htmlFor="csv-platform" hint="Every game in the file">
        <Select
          id="csv-platform"
          value={platform}
          onChange={(e) => onPlatform(e.target.value as CsvPlatform)}
        >
          {PLATFORM_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="CSV file" htmlFor="csv-file">
        <input
          id="csv-file"
          type="file"
          accept=".csv,text/csv"
          onChange={(e) => onFile(e.target.files?.[0] ?? null)}
          className="text-[13px]"
        />
      </Field>
    </div>
  );
}

function ReviewRows({
  preview,
  excludedRows,
  onToggle,
}: {
  preview: CsvPreviewResponse;
  excludedRows: Set<number>;
  onToggle: (rowNumber: number) => void;
}) {
  return (
    <div>
      <p role="status" className="mb-3 text-[13px] text-[var(--ink-soft)]">
        {preview.matched} to add · {preview.needs_review}{" "}
        {preview.needs_review === 1 ? "needs" : "need"} review · {preview.skipped} skipped.
        Untick anything you don&apos;t want.
      </p>
      <ul
        aria-label="CSV rows"
        className="max-h-80 divide-y divide-[var(--border)] overflow-y-auto"
      >
        {preview.rows.map((row) => (
          <ReviewRow
            key={row.row_number}
            row={row}
            isExcluded={excludedRows.has(row.row_number)}
            onToggle={() => onToggle(row.row_number)}
          />
        ))}
      </ul>
    </div>
  );
}

function ReviewRow({
  row,
  isExcluded,
  onToggle,
}: {
  row: CsvRowResult;
  isExcluded: boolean;
  onToggle: () => void;
}) {
  const isSelectable = SELECTABLE.includes(row.status);
  return (
    <li className="flex items-start gap-3 py-2 text-[13px]">
      {isSelectable ? (
        <input
          type="checkbox"
          checked={!isExcluded}
          onChange={onToggle}
          aria-label={`Keep row ${row.row_number}: ${row.title}`}
          className="mt-0.5"
        />
      ) : (
        <span className="w-[13px]" aria-hidden="true" />
      )}
      <div className="min-w-0 flex-1">
        <p className="truncate font-medium">
          <span className="mr-2 text-[var(--ink-faint)]">Row {row.row_number}</span>
          {row.title || <em>(empty)</em>}
        </p>
        {row.game_title && row.game_title !== row.title && (
          <p className="text-[var(--ink-faint)]">Matched: {row.game_title}</p>
        )}
        {row.message && <p className="text-[var(--ink-faint)]">{row.message}</p>}
      </div>
      <span
        className={cx(
          "shrink-0 rounded-full px-2 py-0.5 text-xs font-semibold",
          row.status === "matched" ? "bg-emerald-50 text-emerald-700" : "bg-neutral-100",
        )}
      >
        {STATUS_LABEL[row.status]}
      </span>
    </li>
  );
}

function DoneSummary({ result }: { result: CsvCommitResponse }) {
  return (
    <div role="status" className="text-sm">
      <p className="font-semibold">
        Added {result.added} {result.added === 1 ? "game" : "games"} to your library.
      </p>
      {result.needs_review > 0 && (
        <p className="mt-1 text-[var(--ink-soft)]">
          {result.needs_review} saved for review because they didn&apos;t match one game.
        </p>
      )}
      {result.skipped > 0 && (
        <p className="mt-1 text-[var(--ink-soft)]">{result.skipped} skipped.</p>
      )}
    </div>
  );
}

function Footer({
  step,
  excludedRows,
  isBusy,
  onCancel,
  onBack,
  onReview,
  onCommit,
}: {
  step: Step;
  excludedRows: Set<number>;
  isBusy: boolean;
  onCancel: () => void;
  onBack: () => void;
  onReview: () => void;
  onCommit: (csvText: string) => void;
}) {
  if (step.name === "done") {
    return (
      <Button size="sm" onClick={onCancel}>
        Close
      </Button>
    );
  }
  if (step.name === "choose") {
    return (
      <>
        <Button variant="secondary" size="sm" onClick={onCancel}>
          Cancel
        </Button>
        <Button size="sm" onClick={onReview} loading={isBusy}>
          Review file
        </Button>
      </>
    );
  }
  const keptRows = step.preview.rows.filter(
    (r) => SELECTABLE.includes(r.status) && !excludedRows.has(r.row_number),
  );
  const addCount = keptRows.filter((r) => r.status === "matched").length;
  return (
    <>
      <Button variant="secondary" size="sm" onClick={onBack} disabled={isBusy}>
        Back
      </Button>
      <Button
        size="sm"
        onClick={() => onCommit(step.csvText)}
        loading={isBusy}
        disabled={keptRows.length === 0}
      >
        {addCount > 0 ? `Add ${addCount} ${addCount === 1 ? "game" : "games"}` : "Save for review"}
      </Button>
    </>
  );
}

function errorMessage(err: unknown): string {
  if (err instanceof CsvFileProblem) {
    return err.message;
  }
  if (err instanceof ApiError && err.userMessage) {
    return err.userMessage;
  }
  return FALLBACK_ERROR;
}
