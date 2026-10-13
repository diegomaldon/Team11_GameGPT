// Convenience aliases over the generated OpenAPI schema (see schema.d.ts).
// Regenerate the schema with `npm run gen:api` whenever ../openapi.json changes.
import type { components } from "./schema";

type Schemas = components["schemas"];

export type RecommendRequest = Schemas["RecommendRequest"];
export type RecommendResponse = Schemas["RecommendResponse"];
export type Recommendation = Schemas["Recommendation"];
export type FeedbackRequest = Schemas["FeedbackRequest"];
export type LibraryResponse = Schemas["LibraryResponse"];
export type LibraryItem = Schemas["LibraryItem"];
export type LibrarySyncRequest = Schemas["LibrarySyncRequest"];
export type LibrarySyncResponse = Schemas["LibrarySyncResponse"];
export type Vote = Schemas["Vote"];
export type LibrarySyncJob = Schemas["LibrarySyncJob"];
export type SyncFailure = Schemas["SyncFailure"];
export type SyncJobState = Schemas["SyncJobState"];
export type CsvPlatform = Schemas["CsvImportRequest"]["platform"];
export type CsvPreviewResponse = Schemas["CsvPreviewResponse"];
export type CsvCommitResponse = Schemas["CsvCommitResponse"];
export type CsvRowResult = Schemas["CsvRowResult"];
export type CsvRowStatus = Schemas["CsvRowStatus"];
export type GameSearchResult = Schemas["GameSearchResult"];
export type GameSearchResponse = Schemas["GameSearchResponse"];
export type ManualPlatform = Schemas["ManualAddRequest"]["platform"];
export type ManualAddResponse = Schemas["ManualAddResponse"];
