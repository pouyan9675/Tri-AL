import { describe, expect, it } from "vitest";
import { mockApi } from "@/test/api";
import { ApiError, api, CLIENT_HEADER, unwrap } from "./client";

describe("the API client", () => {
  it("sends the browser-protection header on requests that change something", async () => {
    const { requests } = mockApi({
      "POST /api/jobs/update": () => Response.json({ id: 1 }, { status: 202 }),
      "/api/meta": { installed: true },
    });
    await api.GET("/api/meta");
    await api.POST("/api/jobs/update");
    expect(requests[0]?.headers.get(CLIENT_HEADER)).toBeNull();
    expect(requests[1]?.headers.get(CLIENT_HEADER)).toBe("1");
  });

  it("sends filters as repeated query parameters", async () => {
    const { requests } = mockApi({ "/api/trials": { items: [] } });
    await api.GET("/api/trials", {
      params: { query: { status: ["RECRUITING", "COMPLETED"], limit: 5 } },
    });
    expect(new URL(requests[0]?.url ?? "").search).toBe(
      "?status=RECRUITING&status=COMPLETED&limit=5",
    );
  });

  it("turns an error response into an ApiError with the server's detail", async () => {
    mockApi({
      "/api/meta": () => Response.json({ detail: "there's no data yet" }, { status: 503 }),
    });
    const error = await unwrap(api.GET("/api/meta")).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 503, message: "there's no data yet" });
  });
});
