// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

/**
 * mask-validator.ts
 *
 * Foreground/background discrimination for segmentation masks.
 *
 * Pipeline:
 *   findContours → [contour, ...]
 *     → scoreMaskCandidate()         ← compute per-contour metrics
 *     → isLikelyBackground()         ← reject background contours
 *     → selectForegroundContours()   ← return only plausible objects
 *     → one polygon per contour
 *
 * Design principles:
 *   - Never simply invert all masks.
 *   - Never use "largest area wins".
 *   - Use geometry + coverage + border-contact heuristics.
 *   - Configurable thresholds, not hard-coded per-image values.
 */

/** A 2-D point [x, y]. */
type Point = [number, number];

/** Contour as returned by OpenCV findContours. */
export type Contour = Point[];

/** Metrics computed for one contour. */
export interface ContourProperties {
    /** Number of vertices. */
    vertexCount: number;
    /** Polygon area (shoelace, px²). */
    area: number;
    /** Fraction of image area: area / (imageWidth * imageHeight). */
    coverageRatio: number;
    /** Perimeter (px). */
    perimeter: number;
    /** Centroid [cx, cy]. */
    centroid: Point;
    /** Axis-aligned bounding box. */
    bbox: { left: number; top: number; right: number; bottom: number; width: number; height: number };
    /**
     * Fraction of the perimeter that touches (within 2px of) an image border.
     * Range 0–1. High value → likely the background contour.
     */
    borderContactFraction: number;
    /** Ratio: (4π × area) / perimeter². Range 0–1. 1.0 = perfect circle. */
    compactness: number;
    /** Whether the contour touches ALL 4 image borders. */
    touchesAllBorders: boolean;
}

/** Configuration for foreground selection. */
export interface ForegroundFilterConfig {
    /** Image width in pixels. */
    imageWidth: number;
    /** Image height in pixels. */
    imageHeight: number;
    /**
     * Reject contours whose coverage exceeds this fraction of the image area.
     * Default 0.90 (90 %).  Background contours are almost always > 85 %.
     */
    maxCoverageRatio: number;
    /**
     * Reject contours whose border contact fraction exceeds this value.
     * Default 0.85.  The outermost background contour usually wraps all 4 edges.
     */
    maxBorderContactFraction: number;
    /**
     * Always reject contours touching ALL 4 image borders
     * (these are definitely the outermost background boundary).
     */
    rejectAllBorderTouch: boolean;
    /** Reject contours with area below this value (px²).  Default 500. */
    minAreaPx: number;
    /**
     * Maximum number of foreground components to return.
     * Extra components (ranked by area, smallest first) are dropped.
     */
    maxComponents: number;
}

export const DEFAULT_FOREGROUND_FILTER: ForegroundFilterConfig = {
    imageWidth: 0,
    imageHeight: 0,
    maxCoverageRatio: 0.90,
    maxBorderContactFraction: 0.85,
    rejectAllBorderTouch: true,
    minAreaPx: 500,
    maxComponents: 20,
};

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

/** Shoelace polygon area (absolute value). */
function shoelaceArea(pts: Point[]): number {
    let area = 0;
    const n = pts.length;
    for (let i = 0; i < n; i++) {
        const j = (i + 1) % n;
        area += pts[i][0] * pts[j][1];
        area -= pts[j][0] * pts[i][1];
    }
    return Math.abs(area) / 2;
}

/** Euclidean distance between two points. */
function dist(a: Point, b: Point): number {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    return Math.sqrt(dx * dx + dy * dy);
}

/** Total perimeter of a closed contour. */
function contourPerimeter(pts: Point[]): number {
    if (pts.length < 2) return 0;
    let p = 0;
    for (let i = 0; i < pts.length; i++) {
        p += dist(pts[i], pts[(i + 1) % pts.length]);
    }
    return p;
}

/**
 * Compute the fraction of contour vertices that lie within `margin` pixels
 * of any image border.
 */
function borderContactFraction(
    pts: Point[],
    imageWidth: number,
    imageHeight: number,
    margin = 2,
): number {
    if (pts.length === 0) return 0;
    let touching = 0;
    for (const [x, y] of pts) {
        if (x <= margin || y <= margin || x >= imageWidth - margin || y >= imageHeight - margin) {
            touching++;
        }
    }
    return touching / pts.length;
}

/** Return true if any vertex is within margin of the given border. */
function touchesBorder(
    pts: Point[],
    imageWidth: number,
    imageHeight: number,
    border: 'left' | 'top' | 'right' | 'bottom',
    margin = 2,
): boolean {
    for (const [x, y] of pts) {
        if (border === 'left' && x <= margin) return true;
        if (border === 'top' && y <= margin) return true;
        if (border === 'right' && x >= imageWidth - margin) return true;
        if (border === 'bottom' && y >= imageHeight - margin) return true;
    }
    return false;
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Compute geometric properties for a single contour.
 *
 * @param contour      Contour points [[x,y], ...]
 * @param imageWidth   Full image width in pixels
 * @param imageHeight  Full image height in pixels
 */
export function computeContourProperties(
    contour: Contour,
    imageWidth: number,
    imageHeight: number,
): ContourProperties {
    const n = contour.length;

    if (n < 3) {
        return {
            vertexCount: n,
            area: 0,
            coverageRatio: 0,
            perimeter: 0,
            centroid: [0, 0],
            bbox: {
                left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0,
            },
            borderContactFraction: 0,
            compactness: 0,
            touchesAllBorders: false,
        };
    }

    const area = shoelaceArea(contour);
    const imageArea = imageWidth * imageHeight;
    const perim = contourPerimeter(contour);

    // Centroid
    let cx = 0;
    let cy = 0;
    for (const [x, y] of contour) {
        cx += x;
        cy += y;
    }
    cx /= n;
    cy /= n;

    // Bounding box
    let left = Infinity;
    let top = Infinity;
    let right = -Infinity;
    let bottom = -Infinity;
    for (const [x, y] of contour) {
        if (x < left) left = x;
        if (y < top) top = y;
        if (x > right) right = x;
        if (y > bottom) bottom = y;
    }

    const bcf = borderContactFraction(contour, imageWidth, imageHeight);
    const touchesAll = (
        touchesBorder(contour, imageWidth, imageHeight, 'left') &&
        touchesBorder(contour, imageWidth, imageHeight, 'top') &&
        touchesBorder(contour, imageWidth, imageHeight, 'right') &&
        touchesBorder(contour, imageWidth, imageHeight, 'bottom')
    );

    const compactness = perim > 0 ? (4 * Math.PI * area) / (perim * perim) : 0;

    return {
        vertexCount: n,
        area,
        coverageRatio: imageArea > 0 ? area / imageArea : 0,
        perimeter: perim,
        centroid: [cx, cy],
        bbox: {
            left, top, right, bottom,
            width: right - left,
            height: bottom - top,
        },
        borderContactFraction: bcf,
        compactness,
        touchesAllBorders: touchesAll,
    };
}

/**
 * Return true if a contour is likely the image background rather than a
 * foreground object.
 *
 * Rules (any one is sufficient to classify as background):
 *   1. coverageRatio > maxCoverageRatio
 *   2. borderContactFraction > maxBorderContactFraction
 *   3. rejectAllBorderTouch && touchesAllBorders
 */
export function isLikelyBackground(
    props: ContourProperties,
    config: Pick<ForegroundFilterConfig,
        'maxCoverageRatio' | 'maxBorderContactFraction' | 'rejectAllBorderTouch'
    >,
): boolean {
    if (props.coverageRatio > config.maxCoverageRatio) return true;
    if (props.borderContactFraction > config.maxBorderContactFraction) return true;
    if (config.rejectAllBorderTouch && props.touchesAllBorders) return true;
    return false;
}

/**
 * Filter a list of contours to retain only plausible foreground components.
 *
 * Strategy:
 *   1. Compute properties for each contour.
 *   2. Reject background contours.
 *   3. Reject tiny contours below minAreaPx.
 *   4. Sort remaining by area descending.
 *   5. Return up to maxComponents.
 *
 * @param contours      All contours from findContours (any order).
 * @param config        Filter configuration.
 * @returns             Array of accepted foreground contours.
 */
export function selectForegroundContours(
    contours: Contour[],
    config: ForegroundFilterConfig,
): { contour: Contour; props: ContourProperties }[] {
    const { imageWidth, imageHeight } = config;

    const candidates = contours
        .map((contour) => ({
            contour,
            props: computeContourProperties(contour, imageWidth, imageHeight),
        }))
        .filter(({ props }) => {
            // Reject too-small components
            if (props.area < config.minAreaPx) return false;
            // Reject background
            if (isLikelyBackground(props, config)) return false;
            return true;
        });

    // Sort by area descending (largest foreground object first)
    candidates.sort((a, b) => b.props.area - a.props.area);

    // Limit to maxComponents
    return candidates.slice(0, config.maxComponents);
}

/**
 * Given a set of contours and a user-provided positive point (click location),
 * return ONLY the contour that contains (or is closest to) that point.
 *
 * This is the single-object selection mode used by "Dense Segment".
 *
 * Algorithm:
 *   1. Filter to foreground contours.
 *   2. For each remaining contour, compute distance from posPoint to its centroid.
 *   3. Also compute whether the posPoint lies inside the bounding box.
 *   4. Score = inside_bbox_bonus - dist_to_centroid.
 *   5. Return the highest-scoring contour.
 *
 * @param contours    All contours from findContours.
 * @param posPoint    User's positive click point [x, y].
 * @param config      Filter configuration.
 */
export function selectContourAtPoint(
    contours: Contour[],
    posPoint: Point,
    config: ForegroundFilterConfig,
): { contour: Contour; props: ContourProperties } | null {
    const foreground = selectForegroundContours(contours, config);
    if (foreground.length === 0) return null;
    if (foreground.length === 1) return foreground[0];

    const [px, py] = posPoint;

    let best = foreground[0];
    let bestScore = -Infinity;

    for (const candidate of foreground) {
        const { props } = candidate;
        const {
            centroid: [cx, cy], bbox,
        } = props;

        const distToCentroid = Math.sqrt((px - cx) ** 2 + (py - cy) ** 2);
        const insideBbox = (
            px >= bbox.left && px <= bbox.right &&
            py >= bbox.top && py <= bbox.bottom
        );

        // Points inside bounding box of this component get a large bonus
        const score = (insideBbox ? 10000 : 0) - distToCentroid;

        if (score > bestScore) {
            bestScore = score;
            best = candidate;
        }
    }

    return best;
}

/**
 * Validate whether the full set of returned contours from a model call
 * looks suspicious (potential full-image / background mask).
 *
 * Returns a human-readable warning string, or null if looks OK.
 */
export function detectSuspiciousMask(
    contours: Contour[],
    imageWidth: number,
    imageHeight: number,
): string | null {
    if (contours.length === 0) return null;

    // Compute properties for the largest contour
    const largest = contours.reduce(
        (best, c) => (c.length > best.length ? c : best),
        contours[0],
    );

    const props = computeContourProperties(largest, imageWidth, imageHeight);

    if (props.touchesAllBorders) {
        return `Mask contour touches all 4 image borders — likely a background/inverted mask (coverage: ${(props.coverageRatio * 100).toFixed(1)}%)`;
    }

    if (props.coverageRatio > 0.90) {
        return `Mask covers ${(props.coverageRatio * 100).toFixed(1)}% of the image — likely a background/inverted mask`;
    }

    if (props.borderContactFraction > 0.80) {
        return `${(props.borderContactFraction * 100).toFixed(0)}% of contour perimeter touches image borders — likely background`;
    }

    return null;
}
