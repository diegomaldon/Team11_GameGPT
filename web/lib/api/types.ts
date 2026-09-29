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
