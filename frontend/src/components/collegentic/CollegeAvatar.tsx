import { useState } from "react";
import { cn } from "@/utils";
import type { College } from "@/lib/types";

type Branded = Pick<College, "name" | "logoUrl" | "schoolColors">;

/** Deterministic per-college color, drawn from the navy/orange family, for
 * colleges research hasn't found real school colors for yet — same college
 * always gets the same fallback color across renders. */
const FALLBACK_COLORS = ["#0B1F3A", "#1E3660", "#2A4670", "#DD7A16", "#B8790A", "#5B6B82"];

function fallbackColor(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) >>> 0;
  return FALLBACK_COLORS[hash % FALLBACK_COLORS.length];
}

/** A college's real primary brand color if research found one, else the
 * same deterministic fallback the avatar uses — one accent color per
 * college, shared by every place that wants to color-code by school. */
export function collegeAccentColor(college: Branded): string {
  return college.schoolColors.primary || fallbackColor(college.name);
}

/** logobrands.com's source images (see requirements_agent.py's
 * _fetch_college_logo) are square canvases with a lot of transparent
 * padding around the mark itself, so at the same object-contain sizing
 * they read visibly smaller than a tightly-cropped Wikipedia seal —
 * zoom just these in so both sources fill the chip similarly. */
function isLogobrandsLogo(url: string): boolean {
  return url.includes("logobrands.com");
}

const SIZE_CLASSES = {
  sm: "h-7 w-7 text-xs",
  md: "h-9 w-9 text-sm",
  lg: "h-14 w-14 text-lg",
} as const;

/**
 * The school's real logo (Milestone 19: college_research_agent now looks
 * one up) on a neutral white chip — logos are plain PNGs (a white
 * background is fine, no transparency needed) so the chip keeps them
 * legible against any row/card color. Falls back to a colored initial —
 * either the school's real primary color or a deterministic placeholder —
 * when there's no logo yet, or its URL fails to load.
 */
export function CollegeAvatar({
  college,
  size = "sm",
}: {
  college: Branded;
  size?: keyof typeof SIZE_CLASSES;
}) {
  const [imgFailed, setImgFailed] = useState(false);

  if (college.logoUrl && !imgFailed) {
    return (
      <span
        className={cn(
          "flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-white p-1 ring-1 ring-border",
          SIZE_CLASSES[size]
        )}
      >
        <img
          src={college.logoUrl}
          alt=""
          className={cn(
            "h-full w-full object-contain",
            isLogobrandsLogo(college.logoUrl) && "scale-[1.8] translate-x-[1px]"
          )}
          onError={() => setImgFailed(true)}
        />
      </span>
    );
  }

  return (
    <span
      className={cn(
        "flex shrink-0 items-center justify-center rounded-full font-semibold text-white",
        SIZE_CLASSES[size]
      )}
      style={{ backgroundColor: collegeAccentColor(college) }}
    >
      {college.name.trim().charAt(0).toUpperCase() || "?"}
    </span>
  );
}
