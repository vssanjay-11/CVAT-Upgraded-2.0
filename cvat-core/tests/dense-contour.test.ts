// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import {
    densifyContour,
    removeDuplicatePoints,
    computePerimeter,
    polygonArea,
    hasSelfIntersection,
    flatToPoints,
    contourToPoints,
    validateDensifiedPolygon,
    maskAreaFromRLE,
} from '../src/annotations-actions/dense-contour.ts';
import type { DensifyResult } from '../src/annotations-actions/dense-contour.ts';

describe('Dense Contour Resampling Algorithms', () => {
    describe('removeDuplicatePoints', () => {
        it('should handle empty and single-point lists', () => {
            assert.deepEqual(removeDuplicatePoints([]), []);
            assert.deepEqual(removeDuplicatePoints([[5, 10]]), [[5, 10]]);
        });

        it('should remove consecutive points with distance < epsilon', () => {
            const input: [number, number][] = [
                [0, 0],
                [0.1, 0.1], // within default 0.5 epsilon
                [10, 10],
                [10.2, 10.1], // within epsilon
                [20, 20],
            ];
            const result = removeDuplicatePoints(input, 0.5);
            assert.equal(result.length, 3);
            assert.deepEqual(result[0], [0, 0]);
            assert.deepEqual(result[1], [10, 10]);
            assert.deepEqual(result[2], [20, 20]);
        });

        it('should keep all points if spacing exceeds epsilon', () => {
            const input: [number, number][] = [
                [0, 0],
                [1, 0],
                [2, 0],
                [3, 0],
            ];
            const result = removeDuplicatePoints(input, 0.5);
            assert.equal(result.length, 4);
        });
    });

    describe('computePerimeter', () => {
        it('should return 0 for contours with fewer than 2 points', () => {
            assert.equal(computePerimeter([]), 0);
            assert.equal(computePerimeter([[1, 2]]), 0);
        });

        it('should compute closed perimeter of a 10x10 square as 40', () => {
            const square: [number, number][] = [
                [0, 0],
                [10, 0],
                [10, 10],
                [0, 10],
            ];
            assert.equal(computePerimeter(square, true), 40);
        });

        it('should compute open perimeter of a 10x10 square as 30', () => {
            const square: [number, number][] = [
                [0, 0],
                [10, 0],
                [10, 10],
                [0, 10],
            ];
            assert.equal(computePerimeter(square, false), 30);
        });
    });

    describe('polygonArea', () => {
        it('should return 0 for fewer than 3 vertices', () => {
            assert.equal(polygonArea([]), 0);
            assert.equal(polygonArea([[0, 0], [10, 0]]), 0);
        });

        it('should calculate area of a 20x20 square as 400', () => {
            const square: [number, number][] = [
                [0, 0],
                [20, 0],
                [20, 20],
                [0, 20],
            ];
            assert.equal(polygonArea(square), 400);
        });

        it('should calculate area of a right triangle correctly', () => {
            const triangle: [number, number][] = [
                [0, 0],
                [10, 0],
                [0, 10],
            ];
            assert.equal(polygonArea(triangle), 50);
        });

        it('should return positive area regardless of vertex winding order', () => {
            const cw: [number, number][] = [
                [0, 0],
                [0, 10],
                [10, 10],
                [10, 0],
            ];
            const ccw: [number, number][] = [
                [0, 0],
                [10, 0],
                [10, 10],
                [0, 10],
            ];
            assert.equal(polygonArea(cw), 100);
            assert.equal(polygonArea(ccw), 100);
        });
    });

    describe('hasSelfIntersection', () => {
        it('should return false for convex non-intersecting polygons', () => {
            const square: [number, number][] = [
                [0, 0],
                [10, 0],
                [10, 10],
                [0, 10],
            ];
            assert.equal(hasSelfIntersection(square), false);
        });

        it('should detect self-intersecting hourglass polygon', () => {
            const bowTie: [number, number][] = [
                [0, 0],
                [10, 10],
                [10, 0],
                [0, 10],
            ];
            assert.equal(hasSelfIntersection(bowTie), true);
        });

        it('should return false for < 4 vertices', () => {
            assert.equal(hasSelfIntersection([[0, 0], [1, 1], [2, 0]]), false);
        });
    });

    describe('densifyContour', () => {
        it('should validate invalid argument constraints', () => {
            const pts: [number, number][] = [[0, 0], [10, 0], [10, 10]];
            assert.throws(() => densifyContour(pts, 0, 10, 100), /spacing must be positive/);
            assert.throws(() => densifyContour(pts, -1, 10, 100), /spacing must be positive/);
            assert.throws(() => densifyContour(pts, 2, 2, 100), /minVertices must be >= 3/);
            assert.throws(() => densifyContour(pts, 2, 50, 20), /maxVertices .* must be >= minVertices/);
        });

        it('should resample a 100x100 square with uniform spacing <= requested spacing', () => {
            const square: [number, number][] = [
                [0, 0],
                [100, 0],
                [100, 100],
                [0, 100],
            ];
            const spacing = 2;
            const res: DensifyResult = densifyContour(square, spacing, 10, 1000);

            // Perimeter of 100x100 square is 400
            assert.equal(res.perimeter, 400);

            // Raw count ceil(400 / 2) = 200
            assert.equal(res.vertexCount, 200);

            // Output flat array length should be 200 * 2 = 400
            assert.equal(res.points.length, 400);

            // Max spacing between consecutive vertices should not exceed requested spacing + small delta
            assert.ok(res.maxSpacing <= spacing + 0.01, `Expected maxSpacing <= 2, got ${res.maxSpacing}`);

            // Area should be very close to 10000 (100 * 100)
            assert.ok(Math.abs(res.area - 10000) < 1, `Area mismatch: expected ~10000, got ${res.area}`);
        });

        it('should enforce minVertices floor for small perimeters', () => {
            const tinyTriangle: [number, number][] = [
                [0, 0],
                [1, 0],
                [0, 1],
            ];
            // perimeter ≈ 1 + 1 + 1.414 = 3.414. With spacing 2, rawCount = 2, clamped to minVertices 100
            const res = densifyContour(tinyTriangle, 2, 100, 500);
            assert.equal(res.vertexCount, 100);
            assert.equal(res.points.length, 200);
        });

        it('should enforce maxVertices ceiling for large perimeters', () => {
            const largeSquare: [number, number][] = [
                [0, 0],
                [1000, 0],
                [1000, 1000],
                [0, 1000],
            ];
            // perimeter = 4000. With spacing 1, rawCount = 4000, clamped to maxVertices 500
            const res = densifyContour(largeSquare, 1, 50, 500);
            assert.equal(res.vertexCount, 500);
            assert.equal(res.points.length, 1000);
        });

        it('should handle already-closed contours without creating a duplicate vertex segment', () => {
            const closedSquare: [number, number][] = [
                [0, 0],
                [10, 0],
                [10, 10],
                [0, 10],
                [0, 0], // explicitly closed
            ];
            const res = densifyContour(closedSquare, 2, 10, 100);
            assert.equal(res.perimeter, 40);
            assert.equal(res.vertexCount, 20);
        });

        it('should handle degenerate contours gracefully', () => {
            const resEmpty = densifyContour([], 2, 10, 100);
            assert.equal(resEmpty.vertexCount, 0);
            assert.equal(resEmpty.points.length, 0);

            const resSingle = densifyContour([[5, 5]], 2, 10, 100);
            assert.equal(resSingle.vertexCount, 1);
        });
    });

    describe('Conversion and Validation Helpers', () => {
        it('flatToPoints should pair up coordinate numbers', () => {
            const flat = [1, 2, 3, 4, 5, 6];
            assert.deepEqual(flatToPoints(flat), [[1, 2], [3, 4], [5, 6]]);
        });

        it('contourToPoints should convert tuples to Point array', () => {
            const cvContour: [number, number][] = [[10, 20], [30, 40]];
            assert.deepEqual(contourToPoints(cvContour), [[10, 20], [30, 40]]);
        });

        it('maskAreaFromRLE should calculate sum of foreground runs', () => {
            // RLE format: [0-count, 1-count, 0-count, 1-count, left, top, right, bottom]
            const rle = [10, 25, 5, 30, 0, 0, 100, 100];
            const area = maskAreaFromRLE(rle);
            assert.equal(area, 25 + 30);
        });

        it('validateDensifiedPolygon should flag low vertices', () => {
            const result: DensifyResult = {
                points: [0, 0, 1, 1],
                vertexCount: 2,
                perimeter: 5,
                maxSpacing: 2,
                area: 10,
            };
            const val = validateDensifiedPolygon(result, 10, 0.05);
            assert.equal(val.valid, false);
        });

        it('validateDensifiedPolygon should flag area mismatch exceeding tolerance', () => {
            const result: DensifyResult = {
                points: [0, 0, 10, 0, 10, 10, 0, 10],
                vertexCount: 4,
                perimeter: 40,
                maxSpacing: 10,
                area: 80, // 20% smaller than maskArea of 100
            };
            const val = validateDensifiedPolygon(result, 100, 0.05); // 5% max tolerance
            assert.equal(val.valid, true);
            assert.equal(val.needsReview, true);
            assert.match(val.reason, /Polygon\/mask area mismatch/);
        });

        it('validateDensifiedPolygon should accept well-matched polygons', () => {
            const result: DensifyResult = {
                points: [0, 0, 10, 0, 10, 10, 0, 10],
                vertexCount: 4,
                perimeter: 40,
                maxSpacing: 10,
                area: 99,
            };
            const val = validateDensifiedPolygon(result, 100, 0.05);
            assert.equal(val.valid, true);
            assert.equal(val.needsReview, false);
            assert.equal(val.reason, 'OK');
        });
    });
});
