/** Display names for coded values, from the API's meta (`labels`), so there's no copy here. */
import { useQuery } from "@tanstack/react-query";
import { useCallback } from "react";
import type { Meta } from "@/api/client";
import { metaQuery } from "@/api/queries";
import { countryName, humanize } from "./format";

export type LabelField =
  | "status"
  | "phase"
  | "study_type"
  | "sponsor_class"
  | "intervention_type"
  | "intervention_types"
  | "primary_purpose"
  | "arm_type"
  | "allocation"
  | "intervention_model"
  | "observational_model"
  | "time_perspective"
  | "masking"
  | "masked_role"
  | "countries";

const META_KEYS: Record<string, string> = { intervention_types: "intervention_type" };

export function labelFor(
  meta: Meta | undefined,
  field: string,
  code: string | null | undefined,
): string {
  if (code === null || code === undefined || code === "") return "—";
  if (field === "countries") return countryName(code);
  const labels = meta?.labels[META_KEYS[field] ?? field];
  return labels?.[code] ?? humanize(code);
}

/** `label(field, code)`: a code's display name, or the code made readable. */
export function useLabels() {
  const { data: meta } = useQuery(metaQuery());
  return useCallback(
    (field: string, code: string | null | undefined) => labelFor(meta, field, code),
    [meta],
  );
}
