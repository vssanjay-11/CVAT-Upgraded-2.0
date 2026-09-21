// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

/**
 * Dense contour resampling utilities.
 *
 * Implements arc-length-based interpolation to produce a polygon with uniformly
 * spaced vertices along the original contour boundary.
 *
 * Pipeline:
 *   raw contour points
 *     → remove duplicate consecutive points
 *     → ensure contour is closed (first ≈ last)
 *     → compute cumulative arc lengths
 *     → sample at uniform spacing intervals
 *     → enforce min/max vertex count
 *     → return dense open polygon (first ≠ last)
 */

/** Result statistics returned alongside the densified polygon. */
export interface DensifyResult {
    /** Densified polygon as flat [x0, y0, x1, y1, ...] array. */
    points: number[];
    /** Number of vertices in the densified polygon. */
    vertexCount: number;
    /** Actual perimeter of the input contour in pixels. */
    perimeter: number;
    /** Actual maximum spacing achieved (≤ requested spacing + tolerance). */
    maxSpacing: number;
    /** Polygon area (shoelace formula) in pixels². */
    area: number;
}

/** Pair of (x, y) coordinates. */
type Point = [number, number];

/**
 * Remove consecutive duplicate points from a contour.
 * Two points are considered duplicates if their Euclidean distance < epsilon.
 */
export function removeDuplicatePoints(points: Point[], epsilon = 0.5): Point[] {
    if (points.length === 0) return [];
    const result: Point[] = [points[0]];
    for (let i = 1; i < points.length; i++) {
        const [px, py] = result[result.length - 1];
        const [cx, cy] = points[i];
        const dx = cx - px;
        const dy = cy - py;
        if (Math.sqrt(dx * dx + dy * dy) >= epsilon) {
            result.push(points[i]);
        }
    }
    return result;
}

/**
 * Compute the Euclidean distance between two points.
 */
function dist(a: Point, b: Point): number {
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    return Math.sqrt(dx * dx + dy * dy);
}

/**
 * Compute the total perimeter (arc length) of an open or closed contour.
 * If closed=true, adds the closing segment from last point back to first.
 */
export function computePerimeter(points: Point[], closed = true): number {
    if (points.length < 2) return 0;
    let total = 0;
    for (let i = 0; i < points.length - 1; i++) {
        total += dist(points[i], points[i + 1]);
    }
    if (closed) {
        total += dist(points[points.length - 1], points[0]);
    }
    return total;
}

/**
 * Compute the signed area of a polygon using the shoelace formula.
 * Returns the absolute area value.
 */
export function polygonArea(points: Point[]): number {
    if (points.length < 3) return 0;
    let area = 0;
    const n = points.length;
    for (let i = 0; i < n; i++) {
        const j = (i + 1) % n;
        area += points[i][0] * points[j][1];
        area -= points[j][0] * points[i][1];
    }
    return Math.abs(area) / 2;
}

/**
 * Linearly interpolate between two points at parameter t ∈ [0, 1].
 */
function lerp(a: Point, b: Point, t: number): Point {
    return [
        a[0] + (b[0] - a[0]) * t,
        a[1] + (b[1] - a[1]) * t,
    ];
}

/**
 * Check if two polygon edges (p1→p2) and (p3→p4) intersect,
 * ignoring shared endpoints.
 * Used for lightweight self-intersection detection.
 */
function segmentsIntersect(p1: Point, p2: Point, p3: Point, p4: Point): boolean {
    const d1x = p2[0] - p1[0];
    const d1y = p2[1] - p1[1];
    const d2x = p4[0] - p3[0];
    const d2y = p4[1] - p3[1];

    const cross = d1x * d2y - d1y * d2x;
    if (Math.abs(cross) < 1e-10) return false; // parallel

    const t = ((p3[0] - p1[0]) * d2y - (p3[1] - p1[1]) * d2x) / cross;
    const u = ((p3[0] - p1[0]) * d1y - (p3[1] - p1[1]) * d1x) / cross;

    return t > 1e-10 && t < 1 - 1e-10 && u > 1e-10 && u < 1 - 1e-10;
}

/**
 * Perform a lightweight self-intersection check on a polygon.
 * Only checks O(n) pairs for large polygons (skip-k strategy for performance).
 * Returns true if an intersection is detected.
 */
export function hasSelfIntersection(points: Point[]): boolean {
    const n = points.length;
    if (n < 4) return false;

    // For large polygons use a sampling strategy to keep O(n) complexity
    const step = Math.max(1, Math.floor(n / 200));

    for (let i = 0; i < n; i += step) {
        const a = points[i];
        const b = points[(i + 1) % n];
        for (let j = i + 2; j < n; j += step) {
            if (i === 0 && j === n - 1) continue; // adjacent closing edge
            const c = points[j];
            const d = points[(j + 1) % n];
            if (segmentsIntersect(a, b, c, d)) return true;
        }
    }
    return false;
}

/**
 * Core densification algorithm.
 *
 * Takes an ordered sequence of contour points (as [x,y] pairs) and resamples
 * them at approximately uniform arc-length spacing.
 *
 * @param points        Input contour as [x,y] pairs. May be open or closed.
 * @param spacing       Target maximum distance between consecutive output vertices (px).
 * @param minVertices   Minimum number of output vertices.
 * @param maxVertices   Maximum number of output vertices.
 * @returns             DensifyResult with densified points and statistics.
 */
export function densifyContour(
    points: Point[],
    spacing: number,
    minVertices: number,
    maxVertices: number,
): DensifyResult {
    if (spacing <= 0) {
        throw new Error(`spacing must be positive, got ${spacing}`);
    }
    if (minVertices < 3) {
        throw new Error(`minVertices must be >= 3, got ${minVertices}`);
    }
    if (maxVertices < minVertices) {
        throw new Error(`maxVertices (${maxVertices}) must be >= minVertices (${minVertices})`);
    }

    // Step 1: remove duplicate consecutive points
    const cleaned = removeDuplicatePoints(points, 0.5);

    // Need at least 2 distinct points to form a contour
    if (cleaned.length < 2) {
        return {
            points: cleaned.length === 1 ? [cleaned[0][0], cleaned[0][1], cleaned[0][0], cleaned[0][1], cleaned[0][0], cleaned[0][1]] : [],
            vertexCount: cleaned.length,
            perimeter: 0,
            maxSpacing: 0,
            area: 0,
        };
    }

    // Step 2: ensure the input contour is treated as closed.
    // Build a closed working copy: [p0, p1, ..., pN-1, p0]
    const closedPts: Point[] = [...cleaned];
    // Only add closing segment if last ≠ first
    const closingDist = dist(cleaned[cleaned.length - 1], cleaned[0]);
    const isClosed = closingDist < 0.5;
    if (!isClosed) {
        closedPts.push(cleaned[0]);
    }

    // Step 3: compute cumulative arc lengths along the closed contour
    const segLengths: number[] = [];
    const cumLengths: number[] = [0];
    for (let i = 0; i < closedPts.length - 1; i++) {
        const segLen = dist(closedPts[i], closedPts[i + 1]);
        segLengths.push(segLen);
        cumLengths.push(cumLengths[cumLengths.length - 1] + segLen);
    }
    const perimeter = cumLengths[cumLengths.length - 1];

    if (perimeter < 1e-6) {
        // Degenerate contour
        return {
            points: cleaned.flatMap((p) => [p[0], p[1]]),
            vertexCount: cleaned.length,
            perimeter,
            maxSpacing: 0,
            area: polygonArea(cleaned),
        };
    }

    // Step 4: determine number of target vertices
    // n = ceil(perimeter / spacing), then clamp to [minVertices, maxVertices]
    const rawCount = Math.ceil(perimeter / spacing);
    const targetCount = Math.min(maxVertices, Math.max(minVertices, rawCount));

    // Recompute effective spacing to distribute evenly
    const effectiveSpacing = perimeter / targetCount;

    // Step 5: sample at uniform arc-length positions
    const result: Point[] = [];
    let segIdx = 0; // current segment index in closedPts

    for (let k = 0; k < targetCount; k++) {
        const targetArc = k * effectiveSpacing;

        // Advance segment index until we find the segment containing targetArc
        while (segIdx < cumLengths.length - 2 && cumLengths[segIdx + 1] <= targetArc + 1e-9) {
            segIdx++;
        }

        // Interpolate within the current segment
        const segStart = cumLengths[segIdx];
        const segEnd = cumLengths[segIdx + 1];
        const segLen = segEnd - segStart;

        let t: number;
        if (segLen < 1e-9) {
            t = 0;
        } else {
            t = (targetArc - segStart) / segLen;
            t = Math.max(0, Math.min(1, t)); // clamp to [0, 1]
        }

        result.push(lerp(closedPts[segIdx], closedPts[segIdx + 1], t));
    }

    // Step 6: validate — compute actual max spacing
    let actualMaxSpacing = 0;
    for (let i = 0; i < result.length; i++) {
        const next = (i + 1) % result.length;
        const d = dist(result[i], result[next]);
        if (d > actualMaxSpacing) actualMaxSpacing = d;
    }

    // Step 7: flatten to CVAT polygon flat array [x0,y0,x1,y1,...]
    const flatPoints = result.flatMap((p) => [p[0], p[1]]);

    return {
        points: flatPoints,
        vertexCount: result.length,
        perimeter,
        maxSpacing: actualMaxSpacing,
        area: polygonArea(result),
    };
}

/**
 * Convert a flat CVAT polygon array [x0,y0,x1,y1,...] to Point[] array.
 */
export function flatToPoints(flat: number[]): Point[] {
    const pts: Point[] = [];
    for (let i = 0; i + 1 < flat.length; i += 2) {
        pts.push([flat[i], flat[i + 1]]);
    }
    return pts;
}

/**
 * Convert an OpenCV-style contour [[x,y],...] to a Point[] array.
 * OpenCV contours from CVAT's openCVWrapper are `[number, number][][]`.
 */
export function contourToPoints(contour: [number, number][]): Point[] {
    return contour.map(([x, y]) => [x, y] as Point);
}

/**
 * Validate that a densified polygon meets quality requirements.
 *
 * @param result        DensifyResult from densifyContour()
 * @param maskArea      Area of the original binary mask in pixels².
 * @param maxMismatch   Maximum acceptable fractional area difference (e.g. 0.05 = 5%).
 * @returns             Object with validation status and reason.
 */
export function validateDensifiedPolygon(
    result: DensifyResult,
    maskArea: number,
    maxMismatch: number,
): { valid: boolean; needsReview: boolean; reason: string } {
    if (result.vertexCount < 3) {
        return { valid: false, needsReview: false, reason: 'Too few vertices' };
    }

    if (result.perimeter < 1) {
        return { valid: false, needsReview: false, reason: 'Degenerate contour (near-zero perimeter)' };
    }

    if (maskArea > 0) {
        const diff = Math.abs(result.area - maskArea) / maskArea;
        if (diff > maxMismatch) {
            return {
                valid: true,
                needsReview: true,
                reason: `Polygon/mask area mismatch: ${(diff * 100).toFixed(1)}% > ${(maxMismatch * 100).toFixed(1)}% threshold`,
            };
        }
    }

    return { valid: true, needsReview: false, reason: 'OK' };
}

/**
 * Compute the area of a binary mask from its RLE representation.
 * RLE format: [...counts, left, top, right, bottom]
 * where counts alternate between 0-runs and 1-runs starting with 0.
 */
export function maskAreaFromRLE(rle: Int32Array | number[]): number {
    let area = 0;
    for (let i = 0; i < rle.length - 4; i += 2) {
        // Every odd-indexed run is a 1-valued region
        area += rle[i + 1] ?? 0;
    }
    return area;
}
