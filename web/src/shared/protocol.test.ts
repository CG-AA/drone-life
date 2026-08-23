/** parseEnvelope guards every WS message and the version-skew path. */

import { expect, it, vi } from "vitest";
import { parseEnvelope } from "./protocol";

it("returns a well-formed envelope", () => {
  const msg = parseEnvelope('{"v":1,"type":"world","t":12.5,"data":{"score":3}}');
  expect(msg).not.toBeNull();
  expect(msg!.type).toBe("world");
  expect(msg!.t).toBe(12.5);
  expect(msg!.data).toEqual({ score: 3 });
});

it("swallows garbage without throwing", () => {
  expect(parseEnvelope("{not json")).toBeNull();
  expect(parseEnvelope("")).toBeNull();
  expect(parseEnvelope("null")).toBeNull();
  expect(parseEnvelope('"a bare string"')).toBeNull();
});

it("drops newer-protocol frames and reports the skew", () => {
  const onSkew = vi.fn();
  expect(parseEnvelope('{"v":2,"type":"world","t":0,"data":{}}', onSkew)).toBeNull();
  expect(onSkew).toHaveBeenCalledTimes(1);
});

it("does not call onSkew for matching versions or garbage", () => {
  const onSkew = vi.fn();
  parseEnvelope('{"v":1,"type":"x","t":0,"data":{}}', onSkew);
  parseEnvelope("{broken", onSkew);
  expect(onSkew).not.toHaveBeenCalled();
});
