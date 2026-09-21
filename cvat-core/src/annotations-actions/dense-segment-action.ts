// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

/* eslint-disable @typescript-eslint/no-explicit-any */

/**
 * Dense Segment Action — a BaseCollectionAction that:
 *
 *   For each frame in the job:
 *     1. Calls the configured AI interactor model (via core.lambda.call)
 *     2. Extracts ALL contours from the returned RLE mask using OpenCV
 *     3. Runs foreground/background discrimination (mask-validator)
 *     4. Runs densifyContour() per foreground component
 *     5. Creates one CVAT polygon annotation per accepted foreground component
 *     6. Handles label mapping (explicit > regex > skip)
 *
 * Fixes vs original:
 *   - No longer takes only the longest contour (which was the background).
 *   - No longer breaks after first shape (multiple polygons per frame).
 *   - Uses selectForegroundContours() to reject background/inverted masks.
 *   - Reports NEEDS_REVIEW for suspicious masks instead of creating giant polygons.
 *
 * This action is registered in the CVAT annotations-actions registry so it
 * is available from the Annotations Actions modal for batch job processing
 * (Segment Whole). The single-frame Dense Segment flow is handled directly
 * in the tools-control.tsx UI component without going through this action class.
 */

import ObjectState from '../object-state';
import {
    ShapeType, Source, ModelKind, ObjectType,
} from '../enums';
import { Job, Task } from '../session';
import { SerializedShape } from '../server-response-types';
import {
    ActionParameterType, ActionParameters,
} from './base-action';
import { BaseCollectionAction, CollectionActionInput, CollectionActionOutput } from './base-collection-action';
import { getCollection } from '../annotations';
import {
    densifyContour, contourToPoints, maskAreaFromRLE, validateDensifiedPolygon,
    flatToPoints, polygonArea,
} from './dense-contour';
import {
    selectForegroundContours, detectSuspiciousMask,
    DEFAULT_FOREGROUND_FILTER, ForegroundFilterConfig,
} from './mask-validator';

/** Frame range label assignment rule */
export interface FrameRangeRule {
    from: number;
    to: number;
    labelId: number;
}

/** Settings for one Dense Segment run. Derived from ActionParameters. */
export interface DenseSegmentRunConfig {
    /** Serverless function/model ID (e.g. 'pth-foolwood-siamrpn'). */
    modelId: string;
    /** CVAT label ID to assign to created polygons (0 = range or regex mode). */
    labelId: number;
    /** Maximum inter-vertex spacing in pixels. */
    maxSpacing: number;
    /** Minimum vertex count per polygon. */
    minVertices: number;
    /** Maximum vertex count per polygon. */
    maxVertices: number;
    /** Maximum acceptable polygon/mask area mismatch fraction (0–1). */
    maxAreaMismatch: number;
    /** How to handle existing annotations on each frame. */
    batchBehavior: 'append' | 'replace_matching' | 'replace_all';
    /**
     * Optional JSON-serialized label mapping rules:
     * [{ pattern: string, labelId: number }]
     * Used as fallback when filename-based resolution is needed.
     */
    labelMappingsJson: string;
    /**
     * Optional JSON-serialized frame range rules:
     * [{ from: number, to: number, labelId: number }]
     * Maps frame intervals (e.g. 1-250 -> label A, 500-750 -> label B)
     */
    frameRangeRulesJson?: string;
    /** Frame index mode: 'one_based' (default, e.g. 1-250) or 'zero_based' (0-249). */
    frameRangeIndexMode?: 'one_based' | 'zero_based';
    /** Fallback label ID for frames outside ranges (0 = skip unlisted frames). */
    fallbackLabelId?: number;
    /** Confidence threshold for accepting segmentation masks. */
    confidenceThreshold: number;
    /**
     * Minimum component area in pixels².
     * Components smaller than this are treated as noise and rejected.
     * Default: 500 px²
     */
    minComponentAreaPx?: number;
    /**
     * Maximum coverage ratio (0–1).
     * Masks covering more than this fraction of the image are treated as
     * background/inverted and are rejected (marked NEEDS_REVIEW).
     * Default: 0.90
     */
    maxCoverageRatio?: number;
    /**
     * Maximum number of foreground components to extract per frame.
     * Default: 20
     */
    maxComponentsPerFrame?: number;
}

/** Per-frame processing status, used for reporting. */
export const FrameStatus = {
    PENDING: 'pending',
    PROCESSING: 'processing',
    SUCCESS: 'success',
    SKIPPED: 'skipped',
    FAILED: 'failed',
    NEEDS_REVIEW: 'needs_review',
} as const;
export type FrameStatus = typeof FrameStatus[keyof typeof FrameStatus];

/** Result for a single processed frame. */
export interface FrameResult {
    frame: number;
    status: FrameStatus;
    reason?: string;
    vertexCount?: number;
    perimeter?: number;
    area?: number;
    maskArea?: number;
    /** Number of independent polygon objects created for this frame. */
    objectsCreated?: number;
}

/**
 * Resolve target label for a frame using:
 * 1. Frame Range Rules (e.g. 1-250 -> label A, 500-750 -> label B)
 * 2. Explicit labelId
 * 3. Filename regex mapping rules
 */
export function resolveFrameLabel(
    frameNumber: number,
    frameName: string | undefined,
    config: DenseSegmentRunConfig,
): { labelId: number | null; reason?: string } {
    // 1. Frame Range Rules (highest priority)
    if (config.frameRangeRulesJson) {
        try {
            const ranges = JSON.parse(config.frameRangeRulesJson) as FrameRangeRule[];
            if (Array.isArray(ranges) && ranges.length > 0) {
                const targetFrame = config.frameRangeIndexMode === 'zero_based' ? frameNumber : frameNumber + 1;
                const match = ranges.find((r) => targetFrame >= r.from && targetFrame <= r.to);
                if (match) {
                    return { labelId: match.labelId };
                }
                if (config.fallbackLabelId && config.fallbackLabelId > 0) {
                    return { labelId: config.fallbackLabelId };
                }
                return {
                    labelId: null,
                    reason: `Frame #${frameNumber} (${targetFrame} in ${config.frameRangeIndexMode || '1-based'}) is outside configured frame ranges`,
                };
            }
        } catch {
            // invalid JSON
        }
    }

    // 2. Explicit labelId
    if (config.labelId > 0) {
        return { labelId: config.labelId };
    }

    // 3. Regex mappings
    if (config.labelMappingsJson) {
        try {
            const mappings = JSON.parse(config.labelMappingsJson) as Array<{ pattern: string; labelId: number }>;
            if (frameName && Array.isArray(mappings) && mappings.length > 0) {
                for (const { pattern, labelId } of mappings) {
                    try {
                        if (new RegExp(pattern).test(frameName)) {
                            return { labelId };
                        }
                    } catch {
                        // bad regex
                    }
                }
            }
        } catch {
            // invalid JSON
        }
    }

    return {
        labelId: null,
        reason: 'Could not determine label (no matching range or label configured)',
    };
}

/**
 * Extract ALL foreground contour candidates from a mask (RLE) or polygon shape.
 *
 * Key change vs original: instead of taking the longest (= background) contour,
 * this function passes ALL contours through selectForegroundContours() and
 * returns each accepted one as a separate candidate.
 *
 * @param item        Shape item from the model response
 * @param getContours Function that extracts raw contours from an RLE mask
 * @param filterConfig Foreground filter configuration
 * @returns           Array of { contourPts, maskArea } — one per foreground component
 */
export function extractForegroundContours(
    item: { points: number[]; type: string },
    getContours: (mask: Int32Array) => [number, number][][],
    filterConfig: ForegroundFilterConfig,
): Array<{ contourPts: [number, number][]; maskArea: number }> {
    if (item.type === ShapeType.POLYGON || item.type === 'polygon') {
        // Polygon type: treat the polygon itself as the only component.
        const contourPts = flatToPoints(item.points) as [number, number][];
        if (contourPts.length < 3) return [];
        const maskArea = polygonArea(contourPts);

        // Validate this single polygon against background rules
        const fgCandidates = selectForegroundContours([contourPts], filterConfig);
        if (fgCandidates.length === 0) return [];
        return [{ contourPts, maskArea }];
    }

    if (item.type === ShapeType.MASK || item.type === 'mask') {
        const rleMask = Int32Array.from(item.points);
        if (rleMask.length < 6) return [];

        let allContours: [number, number][][];
        try {
            allContours = getContours(rleMask);
        } catch {
            return [];
        }

        if (!allContours || allContours.length === 0) return [];

        // Compute total mask area for reference
        const totalMaskArea = maskAreaFromRLE(rleMask);

        // Select foreground contours (rejects background, tiny noise, etc.)
        const fgCandidates = selectForegroundContours(allContours, filterConfig);

        // Convert each foreground contour to a component result
        return fgCandidates.map(({ contour }) => {
            const contourPts = contourToPoints(contour);
            const componentArea = polygonArea(contourPts);
            // Use per-component area for validation; fall back to mask area if only one component
            const maskArea = fgCandidates.length === 1 ? totalMaskArea : componentArea;
            return { contourPts, maskArea };
        });
    }

    return [];
}

/**
 * Legacy function kept for backward compatibility.
 * Extracts a single (primary foreground) contour from a shape.
 * Prefer extractForegroundContours() for multi-component support.
 */
export function extractContourFromShape(
    item: { points: number[]; type: string },
    getContours: (mask: Int32Array) => [number, number][][],
): { contourPts: [number, number][]; maskArea: number } | null {
    const components = extractForegroundContours(item, getContours, {
        ...DEFAULT_FOREGROUND_FILTER,
        imageWidth: 99999, // unknown — disable coverage check
        imageHeight: 99999,
        maxCoverageRatio: 1.0,
        maxBorderContactFraction: 1.0,
        rejectAllBorderTouch: false,
    });
    return components.length > 0 ? components[0] : null;
}

/**
 * DenseSegmentAction — BatchCollectionAction for Segment Whole.
 *
 * Works as a CollectionAction that, unlike shape-based actions, needs to
 * CREATE new shapes rather than modify existing ones. It therefore:
 * - Does not need input collection shapes to operate (they may be empty)
 * - Calls the AI interactor per frame
 * - Returns created shapes for commit
 */
export class DenseSegmentAction extends BaseCollectionAction {
    #config: DenseSegmentRunConfig | null = null;
    #instance: Job | Task | null = null;
    #frameResults: FrameResult[] = [];

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    #lambdaCall: ((taskId: number, model: any, args: object) => Promise<any>) | null = null;
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    #getContours: ((mask: Int32Array) => [number, number][][]) | null = null;

    public get name(): string {
        return 'Dense Segment';
    }

    public get parameters(): ActionParameters | null {
        return {
            'Model ID': {
                type: ActionParameterType.SELECT,
                values: ({ instance }: { instance: Job | Task }) => {
                    // Returns empty array — values are populated dynamically in the UI
                    // from the list of available interactor models.
                    void instance;
                    return [];
                },
                defaultValue: '',
            },
            'Label ID': {
                type: ActionParameterType.NUMBER,
                values: ['0', '999999', '1'],
                defaultValue: '0',
            },
            'Max Vertex Spacing (px)': {
                type: ActionParameterType.NUMBER,
                values: ['1', '50', '0.5'],
                defaultValue: '2',
            },
            'Min Vertices': {
                type: ActionParameterType.NUMBER,
                values: ['3', '10000', '1'],
                defaultValue: '100',
            },
            'Max Vertices': {
                type: ActionParameterType.NUMBER,
                values: ['3', '100000', '1'],
                defaultValue: '5000',
            },
            'Max Area Mismatch (%)': {
                type: ActionParameterType.NUMBER,
                values: ['0', '100', '0.5'],
                defaultValue: '5',
            },
            'Confidence Threshold': {
                type: ActionParameterType.NUMBER,
                values: ['0', '1', '0.01'],
                defaultValue: '0.5',
            },
            'Batch Behavior': {
                type: ActionParameterType.SELECT,
                values: ['append', 'replace_matching', 'replace_all'],
                defaultValue: 'replace_matching',
            },
            'Label Mappings JSON': {
                type: ActionParameterType.SELECT,
                values: [],
                defaultValue: '[]',
            },
            'Min Component Area (px²)': {
                type: ActionParameterType.NUMBER,
                values: ['0', '100000', '100'],
                defaultValue: '500',
            },
            'Max Coverage Ratio (%)': {
                type: ActionParameterType.NUMBER,
                values: ['50', '100', '1'],
                defaultValue: '90',
            },
        };
    }

    public isApplicableForObject(_objectState: ObjectState): boolean {
        // Dense Segment creates new objects; it doesn't modify existing ones
        return false;
    }

    /**
     * Initialize the action with parameters and resolve dependencies.
     * We use dynamic imports to avoid circular dependency issues.
     */
    public async init(
        instance: Job | Task,
        parameters: Record<string, string | number>,
    ): Promise<void> {
        this.#instance = instance;
        this.#frameResults = [];

        this.#config = {
            modelId: String(parameters['Model ID'] || ''),
            labelId: Number(parameters['Label ID'] || 0),
            maxSpacing: Number(parameters['Max Vertex Spacing (px)'] || 2),
            minVertices: Math.max(3, Number(parameters['Min Vertices'] || 100)),
            maxVertices: Number(parameters['Max Vertices'] || 5000),
            maxAreaMismatch: Number(parameters['Max Area Mismatch (%)'] || 5) / 100,
            batchBehavior: (parameters['Batch Behavior'] as DenseSegmentRunConfig['batchBehavior']) || 'replace_matching',
            labelMappingsJson: String(parameters['Label Mappings JSON'] || '[]'),
            confidenceThreshold: Number(parameters['Confidence Threshold'] || 0.5),
            minComponentAreaPx: Number(parameters['Min Component Area (px²)'] || 500),
            maxCoverageRatio: Number(parameters['Max Coverage Ratio (%)'] || 90) / 100,
            maxComponentsPerFrame: 20,
        };

        // Dynamically resolve lambda.call to avoid circular imports
        // eslint-disable-next-line @typescript-eslint/no-var-requires
        const lambdaManager = (await import('../lambda-manager')).default;
        this.#lambdaCall = (taskId, model, args) => lambdaManager.call(taskId, model, args);

        // Default contour extractor — replaced by setContourExtractor() in browser context
        this.#getContours = (_mask: Int32Array): [number, number][][] => [];
    }

    /** Set the contour extraction function (injected by browser-side code). */
    public setContourExtractor(fn: (mask: Int32Array) => [number, number][][]): void {
        this.#getContours = fn;
    }

    public async destroy(): Promise<void> {
        this.#instance = null;
        this.#config = null;
        this.#lambdaCall = null;
        this.#getContours = null;
    }

    /**
     * applyFilter: for Dense Segment we don't filter based on existing collection.
     * We accept the full collection (including empty) and will create new shapes.
     */
    public applyFilter(input: Pick<CollectionActionInput, 'collection' | 'frameData'>): CollectionActionInput['collection'] {
        // Pass through all shapes unfiltered — we use them only for replace_matching/replace_all
        return input.collection;
    }

    /**
     * Resolve which label to apply for a given frame.
     */
    private resolveLabelId(frameNumber: number, frameFileName: string | undefined): { labelId: number | null; reason?: string } {
        return resolveFrameLabel(frameNumber, frameFileName, this.#config!);
    }

    /**
     * Process a single frame: call the AI model, extract ALL foreground contours,
     * densify each, return one SerializedShape per accepted component.
     */
    private async processFrame(
        frameNumber: number,
        frameFileName: string | undefined,
        existingShapes: SerializedShape[],
        onProgress: (msg: string, pct: number) => void,
    ): Promise<{
        created: SerializedShape[];
        deleted: SerializedShape[];
        status: FrameStatus;
        reason?: string;
    }> {
        const config = this.#config!;
        const instance = this.#instance!;

        // Resolve fallback frame-level label (e.g. from explicit config or ranges)
        const resolved = this.resolveLabelId(frameNumber, frameFileName);
        const resolvedLabelId = resolved.labelId;

        onProgress(`Frame ${frameNumber}: Calling segmentation model...`, 0);

        let interactorResult: { shapes: Array<{ points: number[]; type: string; attributes: Array<{ spec_id: number; value: string }> }> };
        let frameWidth = 1920;
        let frameHeight = 1080;

        try {
            // eslint-disable-next-line @typescript-eslint/no-var-requires
            const lambdaManager = (await import('../lambda-manager')).default;
            const { models } = await lambdaManager.list();
            const model = models.find((m: any) => m.id === config.modelId || m.kind === ModelKind.INTERACTOR);

            if (!model) {
                return {
                    created: [],
                    deleted: [],
                    status: FrameStatus.SKIPPED,
                    reason: `Model "${config.modelId}" not found. Available models: ${models.map((m: any) => m.id).join(', ')}`,
                };
            }

            const taskId = instance instanceof Job ? instance.taskId : instance.id;
            const jobId = instance instanceof Job ? instance.id : undefined;

            // Get frame metadata for image dimensions
            const frameData = await Object.getPrototypeOf(instance).frames
                .get.implementation.call(instance, frameNumber);

            frameWidth = frameData.width || frameWidth;
            frameHeight = frameData.height || frameHeight;

            const cx = Math.floor(frameWidth / 2);
            const cy = Math.floor(frameHeight / 2);
            const multiProbePoints: [number, number][] = [
                [cx, cy],
                [Math.floor(frameWidth * 0.25), Math.floor(frameHeight * 0.25)],
                [Math.floor(frameWidth * 0.75), Math.floor(frameHeight * 0.25)],
                [Math.floor(frameWidth * 0.25), Math.floor(frameHeight * 0.75)],
                [Math.floor(frameWidth * 0.75), Math.floor(frameHeight * 0.75)],
                [Math.floor(frameWidth * 0.5), Math.floor(frameHeight * 0.25)],
                [Math.floor(frameWidth * 0.5), Math.floor(frameHeight * 0.75)],
                [Math.floor(frameWidth * 0.25), Math.floor(frameHeight * 0.5)],
                [Math.floor(frameWidth * 0.75), Math.floor(frameHeight * 0.5)],
            ];

            interactorResult = await this.#lambdaCall!(taskId, model, {
                type: 'segment_whole',
                mode: 'all_components',
                frame: frameNumber,
                pos_points: multiProbePoints,
                neg_points: [],
                obj_bbox: [],
                ...(jobId !== undefined ? { job: jobId } : {}),
            }) as typeof interactorResult;
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            return {
                created: [],
                deleted: [],
                status: FrameStatus.FAILED,
                reason: `Model call failed: ${msg}`,
            };
        }

        // Build foreground filter config using actual image dimensions
        const filterConfig: ForegroundFilterConfig = {
            ...DEFAULT_FOREGROUND_FILTER,
            imageWidth: frameWidth,
            imageHeight: frameHeight,
            minAreaPx: config.minComponentAreaPx ?? DEFAULT_FOREGROUND_FILTER.minAreaPx,
            maxCoverageRatio: config.maxCoverageRatio ?? DEFAULT_FOREGROUND_FILTER.maxCoverageRatio,
            maxComponents: config.maxComponentsPerFrame ?? DEFAULT_FOREGROUND_FILTER.maxComponents,
        };

        // Process ALL returned mask/polygon shapes from the model
        let createdShapes: SerializedShape[] = [];

        for (const item of (interactorResult?.shapes ?? [])) {
            // Check confidence
            const confidenceAttr = item.attributes?.find((a) => a.spec_id === 0);
            const confidence = confidenceAttr ? +confidenceAttr.value : 1;
            if (confidence < config.confidenceThreshold) continue;

            onProgress(`Frame ${frameNumber}: Analyzing mask...`, 20);

            // Quick suspicious-mask check
            if (item.type === ShapeType.MASK || item.type === 'mask') {
                try {
                    const rleMask = Int32Array.from(item.points);
                    if (rleMask.length >= 6) {
                        const rawContours = this.#getContours!(rleMask);
                        const warning = detectSuspiciousMask(rawContours, frameWidth, frameHeight);
                        if (warning) {
                            // Mark suspicious but still attempt foreground extraction
                            this.#frameResults.push({
                                frame: frameNumber,
                                status: FrameStatus.NEEDS_REVIEW,
                                reason: `Suspicious mask: ${warning}`,
                            });
                        }
                    }
                } catch {
                    // continue anyway
                }
            }

            onProgress(`Frame ${frameNumber}: Extracting foreground components...`, 30);

            // Extract ALL foreground components
            const components = extractForegroundContours(item, this.#getContours!, filterConfig);

            if (components.length === 0) {
                // No foreground found — possibly all-background mask
                continue;
            }

            onProgress(`Frame ${frameNumber}: Densifying ${components.length} component(s)...`, 60);

            // Create one polygon per foreground component
            for (const { contourPts, maskArea } of components) {
                let densifyResult;
                try {
                    densifyResult = densifyContour(
                        contourPts,
                        config.maxSpacing,
                        config.minVertices,
                        config.maxVertices,
                    );
                } catch {
                    continue;
                }

                if (densifyResult.vertexCount < 3) continue;

                const validation = validateDensifiedPolygon(densifyResult, maskArea, config.maxAreaMismatch);
                if (!validation.valid) continue;

                // Resolve per-instance label: Model detection takes precedence
                let itemLabelId: number | null = null;
                const classNameAttr = item.attributes?.find(
                    (a: any) => a.name === 'class_name' || a.spec_id === 1,
                );
                const classIdAttr = item.attributes?.find(
                    (a: any) => a.name === 'class_id' || a.spec_id === 2,
                );
                const labelIdAttr = item.attributes?.find(
                    (a: any) => a.name === 'label_id' || a.spec_id === 3,
                );

                // 1. Backend-provided label_id if valid
                if (typeof (item as any).label_id === 'number' && (item as any).label_id > 0) {
                    itemLabelId = (item as any).label_id;
                } else if (labelIdAttr && !isNaN(+labelIdAttr.value) && +labelIdAttr.value > 0) {
                    itemLabelId = +labelIdAttr.value;
                }

                // 2. Backend class_name -> CVAT label-name matching
                const instanceLabels = (instance as any).labels || [];
                const cName = (item as any).class_name || classNameAttr?.value;
                if (!itemLabelId && cName) {
                    const targetName = String(cName).trim().toLowerCase();
                    const matched = instanceLabels.find(
                        (l: any) => l.name.trim().toLowerCase() === targetName,
                    );
                    if (matched) {
                        itemLabelId = matched.id;
                    }
                }

                // 3. Backend class_id -> configured model-class mapping (0 -> TRANSMISSION HOUSING, 1 -> PLV BODY)
                const cId = (item as any).class_id !== undefined ? (item as any).class_id : classIdAttr?.value;
                if (!itemLabelId && cId !== undefined) {
                    const clsIdNum = parseInt(cId, 10);
                    const defaultName = clsIdNum === 0 ? 'transmission housing' : (clsIdNum === 1 ? 'plv body' : null);
                    if (defaultName) {
                        const matched = instanceLabels.find(
                            (l: any) => l.name.trim().toLowerCase() === defaultName,
                        );
                        if (matched) {
                            itemLabelId = matched.id;
                        }
                    }
                }

                // 4. Existing UI/frame-level resolvedLabelId as fallback only
                if (!itemLabelId && resolvedLabelId) {
                    itemLabelId = resolvedLabelId;
                }

                // 5. If no valid label can be resolved, reject/skip that individual shape
                if (!itemLabelId) {
                    continue;
                }

                const shape: SerializedShape = {
                    label_id: itemLabelId,
                    group: 0,
                    frame: frameNumber,
                    source: Source.AUTO,
                    attributes: [],
                    elements: [],
                    occluded: false,
                    outside: false,
                    points: densifyResult.points,
                    rotation: 0,
                    z_order: 0,
                    type: ShapeType.POLYGON,
                };

                createdShapes.push(shape);

                this.#frameResults.push({
                    frame: frameNumber,
                    status: validation.needsReview ? FrameStatus.NEEDS_REVIEW : FrameStatus.SUCCESS,
                    reason: validation.reason,
                    vertexCount: densifyResult.vertexCount,
                    perimeter: densifyResult.perimeter,
                    area: densifyResult.area,
                    maskArea,
                    objectsCreated: components.length,
                });
            }
        }

        // Domain Rule: Only ONE component label type per frame. Drop conflicting detections.
        if (createdShapes.length > 1) {
            const labelCounts = new Map<number, number>();
            for (const sh of createdShapes) {
                labelCounts.set(sh.label_id, (labelCounts.get(sh.label_id) || 0) + 1);
            }
            if (labelCounts.size > 1) {
                let dominantLabelId = createdShapes[0].label_id;
                let maxCount = 0;
                for (const [lid, count] of labelCounts.entries()) {
                    if (count > maxCount) {
                        maxCount = count;
                        dominantLabelId = lid;
                    }
                }
                createdShapes = createdShapes.filter((sh) => sh.label_id === dominantLabelId);
            }
        }

        // Domain Rule: Only 1 to 4 instances of the component per frame
        if (createdShapes.length > 4) {
            createdShapes = createdShapes.slice(0, 4);
        }

        if (createdShapes.length === 0) {
            return {
                created: [],
                deleted: [],
                status: FrameStatus.SKIPPED,
                reason: 'No valid foreground components found in model response (mask may have been background or unmapped label)',
            };
        }

        // Determine which existing shapes to delete based on batchBehavior
        let toDelete: SerializedShape[] = [];
        if (config.batchBehavior === 'replace_all') {
            toDelete = existingShapes;
        } else if (config.batchBehavior === 'replace_matching') {
            const createdLabelIds = new Set(createdShapes.map((s) => s.label_id));
            if (resolvedLabelId) createdLabelIds.add(resolvedLabelId);
            toDelete = existingShapes.filter((s) => createdLabelIds.has(s.label_id));
        }

        const overallStatus = this.#frameResults
            .filter((r) => r.frame === frameNumber)
            .some((r) => r.status === FrameStatus.NEEDS_REVIEW)
            ? FrameStatus.NEEDS_REVIEW
            : FrameStatus.SUCCESS;

        return {
            created: createdShapes,
            deleted: toDelete,
            status: overallStatus,
        };
    }

    /**
     * run() — called by the annotations-actions framework per-frame.
     *
     * Produces multiple new polygon shapes (one per foreground component).
     */
    public async run(input: CollectionActionInput): Promise<CollectionActionOutput> {
        const { onProgress, cancelled, collection } = input;

        if (cancelled()) {
            return { created: { shapes: [], tags: [], tracks: [] }, deleted: { shapes: [], tags: [], tracks: [] } };
        }

        const frameNumber = input.frameData.number;
        const frameFileName: string | undefined = undefined;

        onProgress(`Processing frame ${frameNumber}...`, 0);

        const result = await this.processFrame(frameNumber, frameFileName, collection.shapes, onProgress);

        return {
            created: { shapes: result.created, tags: [], tracks: [] },
            deleted: { shapes: result.deleted, tags: [], tracks: [] },
        };
    }

    /** Get per-frame results after the action has run. */
    public get frameResults(): FrameResult[] {
        return [...this.#frameResults];
    }
}

/**
 * Standalone function to run Dense Segment over all frames in a job.
 * This is the implementation behind the "Segment Whole" UI feature.
 *
 * KEY FIX: This now creates MULTIPLE polygons per frame when multiple
 * independent foreground components are found. The `break` that limited
 * output to one polygon per frame has been removed.
 */
export async function runDenseSegmentWhole(
    jobInstance: Job,
    config: DenseSegmentRunConfig,
    getContours: (mask: Int32Array) => [number, number][][],
    onFrameProgress: (frameIdx: number, totalFrames: number, status: FrameStatus, message: string) => void,
    onSaveProgress: (message: string) => void,
    cancelled: () => boolean,
): Promise<{
    processed: number;
    successful: number;
    skipped: number;
    failed: number;
    needsReview: number;
    objectsCreated: number;
    frameResults: FrameResult[];
}> {
    // eslint-disable-next-line @typescript-eslint/no-var-requires
    const lambdaManager = (await import('../lambda-manager')).default;
    const { models } = await lambdaManager.list();

    const model = config.modelId
        ? models.find((m: any) => m.id === config.modelId)
        : models.find((m: any) => m.kind === ModelKind.INTERACTOR);

    if (!model) {
        throw new Error(`No suitable interactor model found. Configured model: "${config.modelId}"`);
    }

    const rawFrameNumbers: number[] = await jobInstance.frames.frameNumbers();
    const totalFrames = rawFrameNumbers.length;

    const frameResults: FrameResult[] = [];
    let successful = 0;
    let skipped = 0;
    let failed = 0;
    let needsReview = 0;
    let objectsCreated = 0;

    const SAVE_BATCH_SIZE = 10;
    const pendingSaves: { frameNumber: number; shapes: SerializedShape[]; deletes?: SerializedShape[] }[] = [];

    const flushSaves = async (): Promise<void> => {
        if (pendingSaves.length === 0) return;
        onSaveProgress(`Saving ${pendingSaves.length} frame batch...`);

        const toCreate: SerializedShape[] = pendingSaves.flatMap((b) => b.shapes);
        const toDelete: SerializedShape[] = pendingSaves.flatMap((b) => b.deletes || []);

        if (toCreate.length > 0 || toDelete.length > 0) {
            await jobInstance.annotations.commit(
                { shapes: toCreate, tags: [], tracks: [] },
                { shapes: toDelete, tags: [], tracks: [] },
                pendingSaves[0].frameNumber,
            );
        }

        pendingSaves.length = 0;
        await jobInstance.annotations.save(() => {});
    };

    for (let frameIdx = 0; frameIdx < totalFrames; frameIdx++) {
        if (cancelled()) {
            try { await flushSaves(); } catch { /* best effort */ }
            break;
        }

        const frameNumber = rawFrameNumbers[frameIdx];

        let frameData: any;
        try {
            frameData = await Object.getPrototypeOf(jobInstance).frames
                .get.implementation.call(jobInstance, frameNumber);
        } catch (err) {
            const msg = err instanceof Error ? err.message : String(err);
            frameResults.push({ frame: frameNumber, status: FrameStatus.FAILED, reason: `Could not load frame metadata: ${msg}` });
            failed++;
            onFrameProgress(frameIdx, totalFrames, FrameStatus.FAILED, `Frame ${frameNumber}: Failed to load`);
            continue;
        }

        if (frameData.deleted) {
            frameResults.push({ frame: frameNumber, status: FrameStatus.SKIPPED, reason: 'Frame is deleted' });
            skipped++;
            onFrameProgress(frameIdx, totalFrames, FrameStatus.SKIPPED, `Frame ${frameNumber}: Deleted`);
            continue;
        }

        const frameName: string | undefined = frameData.filename || frameData.name;
        // Resolve fallback frame-level label (e.g. from explicit config or ranges)
        const resolved = resolveFrameLabel(frameNumber, frameName, config);
        const resolvedLabelId = resolved.labelId;

        // Query existing shapes on this frame to support replace_matching and replace_all
        let frameExistingShapes: SerializedShape[] = [];
        if (config.batchBehavior !== 'append') {
            try {
                const states: ObjectState[] = await jobInstance.annotations.get(frameNumber, false, []);
                const exported = await Promise.all(
                    states
                        .filter((s) => s.objectType === ObjectType.SHAPE)
                        .map((s) => s.export() as Promise<SerializedShape>),
                );
                frameExistingShapes = exported;
            } catch {
                frameExistingShapes = [];
            }
        }

        onFrameProgress(frameIdx, totalFrames, FrameStatus.PROCESSING, `Frame ${frameNumber}: Segmenting...`);

        const frameWidth: number = frameData.width || 1920;
        const frameHeight: number = frameData.height || 1080;

        // Build foreground filter config for this frame
        const filterConfig: ForegroundFilterConfig = {
            ...DEFAULT_FOREGROUND_FILTER,
            imageWidth: frameWidth,
            imageHeight: frameHeight,
            minAreaPx: config.minComponentAreaPx ?? DEFAULT_FOREGROUND_FILTER.minAreaPx,
            maxCoverageRatio: config.maxCoverageRatio ?? DEFAULT_FOREGROUND_FILTER.maxCoverageRatio,
            maxComponents: config.maxComponentsPerFrame ?? DEFAULT_FOREGROUND_FILTER.maxComponents,
        };

        let interactorResult: any;
        try {
            const cx = Math.floor(frameWidth / 2);
            const cy = Math.floor(frameHeight / 2);
            const multiProbePoints: [number, number][] = [
                [cx, cy],
                [Math.floor(frameWidth * 0.25), Math.floor(frameHeight * 0.25)],
                [Math.floor(frameWidth * 0.75), Math.floor(frameHeight * 0.25)],
                [Math.floor(frameWidth * 0.25), Math.floor(frameHeight * 0.75)],
                [Math.floor(frameWidth * 0.75), Math.floor(frameHeight * 0.75)],
                [Math.floor(frameWidth * 0.5), Math.floor(frameHeight * 0.25)],
                [Math.floor(frameWidth * 0.5), Math.floor(frameHeight * 0.75)],
                [Math.floor(frameWidth * 0.25), Math.floor(frameHeight * 0.5)],
                [Math.floor(frameWidth * 0.75), Math.floor(frameHeight * 0.5)],
            ];

            interactorResult = await lambdaManager.call(jobInstance.taskId, model, {
                type: 'segment_whole',
                mode: 'all_components',
                frame: frameNumber,
                pos_points: multiProbePoints,
                neg_points: [],
                obj_bbox: [],
                job: jobInstance.id,
            });
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            frameResults.push({ frame: frameNumber, status: FrameStatus.FAILED, reason: `Model call failed: ${msg}` });
            failed++;
            onFrameProgress(frameIdx, totalFrames, FrameStatus.FAILED, `Frame ${frameNumber}: Model failed`);
            continue;
        }

        // Collect all shapes created for this frame
        const frameShapes: SerializedShape[] = [];
        let frameSuspicious = false;

        for (const item of (interactorResult?.shapes ?? [])) {
            const confidenceAttr = item.attributes?.find((a: any) => a.spec_id === 0);
            const confidence = confidenceAttr ? +confidenceAttr.value : 1;
            if (confidence < config.confidenceThreshold) continue;

            // Suspicious mask check
            if (item.type === ShapeType.MASK || item.type === 'mask') {
                try {
                    const rleMask = Int32Array.from(item.points);
                    if (rleMask.length >= 6) {
                        const rawContours = getContours(rleMask);
                        const warning = detectSuspiciousMask(rawContours, frameWidth, frameHeight);
                        if (warning) {
                            frameSuspicious = true;
                        }
                    }
                } catch { /* continue */ }
            }

            // Extract ALL foreground components — this is the KEY FIX
            const components = extractForegroundContours(item, getContours, filterConfig);

            for (const { contourPts, maskArea } of components) {
                let densifyResult;
                try {
                    densifyResult = densifyContour(
                        contourPts,
                        config.maxSpacing,
                        config.minVertices,
                        config.maxVertices,
                    );
                } catch {
                    continue;
                }

                if (densifyResult.vertexCount < 3) continue;

                const validation = validateDensifiedPolygon(densifyResult, maskArea, config.maxAreaMismatch);
                if (!validation.valid) continue;

                // Resolve per-instance label: Model detection takes precedence
                let itemLabelId: number | null = null;
                const classNameAttr = item.attributes?.find(
                    (a: any) => a.name === 'class_name' || a.spec_id === 1,
                );
                const classIdAttr = item.attributes?.find(
                    (a: any) => a.name === 'class_id' || a.spec_id === 2,
                );
                const labelIdAttr = item.attributes?.find(
                    (a: any) => a.name === 'label_id' || a.spec_id === 3,
                );

                // 1. Backend-provided label_id if valid
                if (typeof (item as any).label_id === 'number' && (item as any).label_id > 0) {
                    itemLabelId = (item as any).label_id;
                } else if (labelIdAttr && !isNaN(+labelIdAttr.value) && +labelIdAttr.value > 0) {
                    itemLabelId = +labelIdAttr.value;
                }

                // 2. Backend class_name -> CVAT label-name matching
                const jobLabels = jobInstance.labels || [];
                if (!itemLabelId && classNameAttr && classNameAttr.value) {
                    const targetName = String(classNameAttr.value).trim().toLowerCase();
                    const matched = jobLabels.find(
                        (l: any) => l.name.trim().toLowerCase() === targetName,
                    );
                    if (matched) {
                        itemLabelId = matched.id;
                    }
                }

                // 3. Backend class_id -> configured model-class mapping (0 -> TRANSMISSION HOUSING, 1 -> PLV BODY)
                if (!itemLabelId && classIdAttr && classIdAttr.value !== undefined) {
                    const clsIdNum = parseInt(classIdAttr.value, 10);
                    const defaultName = clsIdNum === 0 ? 'transmission housing' : (clsIdNum === 1 ? 'plv body' : null);
                    if (defaultName) {
                        const matched = jobLabels.find(
                            (l: any) => l.name.trim().toLowerCase() === defaultName,
                        );
                        if (matched) {
                            itemLabelId = matched.id;
                        }
                    }
                }

                // 4. Existing UI/frame-level resolvedLabelId as fallback only
                if (!itemLabelId && resolvedLabelId) {
                    itemLabelId = resolvedLabelId;
                }

                // 5. If no valid label can be resolved, reject/skip that individual shape
                if (!itemLabelId) {
                    continue;
                }

                const newShape: SerializedShape = {
                    label_id: itemLabelId,
                    group: 0,
                    frame: frameNumber,
                    source: Source.AUTO,
                    attributes: [],
                    elements: [],
                    occluded: false,
                    outside: false,
                    points: densifyResult.points,
                    rotation: 0,
                    z_order: 0,
                    type: ShapeType.POLYGON,
                };

                frameShapes.push(newShape);

                const componentStatus = (frameSuspicious || validation.needsReview)
                    ? FrameStatus.NEEDS_REVIEW
                    : FrameStatus.SUCCESS;

                frameResults.push({
                    frame: frameNumber,
                    status: componentStatus,
                    reason: validation.needsReview ? validation.reason : (frameSuspicious ? 'Suspicious mask — review recommended' : 'OK'),
                    vertexCount: densifyResult.vertexCount,
                    perimeter: densifyResult.perimeter,
                    area: densifyResult.area,
                    maskArea,
                    objectsCreated: components.length,
                });
            }
        }

        if (frameShapes.length === 0) {
            // No valid foreground found for this frame
            if (!frameResults.some((r) => r.frame === frameNumber)) {
                frameResults.push({
                    frame: frameNumber,
                    status: frameSuspicious ? FrameStatus.NEEDS_REVIEW : FrameStatus.SKIPPED,
                    reason: frameSuspicious
                        ? 'Suspicious mask (likely background) — no valid foreground found'
                        : 'No valid foreground components detected',
                });
            }
            if (frameSuspicious) {
                needsReview++;
            } else {
                skipped++;
            }
            onFrameProgress(
                frameIdx, totalFrames,
                frameSuspicious ? FrameStatus.NEEDS_REVIEW : FrameStatus.SKIPPED,
                `Frame ${frameNumber}: ${frameSuspicious ? 'Suspicious mask' : 'No valid mask'}`,
            );
        } else {
            // Shapes were found — record success
            const frameHasReview = frameShapes.length > 0 && (
                frameSuspicious ||
                frameResults
                    .filter((r) => r.frame === frameNumber)
                    .some((r) => r.status === FrameStatus.NEEDS_REVIEW)
            );

            if (frameHasReview) {
                needsReview++;
            } else {
                successful++;
            }

            objectsCreated += frameShapes.length;

            // Determine which existing shapes to delete on this frame based on batchBehavior
            let frameDeletes: SerializedShape[] = [];
            if (config.batchBehavior === 'replace_all') {
                frameDeletes = frameExistingShapes;
            } else if (config.batchBehavior === 'replace_matching') {
                const createdLabelIds = new Set(frameShapes.map((s) => s.label_id));
                if (resolvedLabelId) createdLabelIds.add(resolvedLabelId);
                frameDeletes = frameExistingShapes.filter((s) => createdLabelIds.has(s.label_id));
            }

            pendingSaves.push({ frameNumber, shapes: frameShapes, deletes: frameDeletes });

            onFrameProgress(
                frameIdx, totalFrames,
                frameHasReview ? FrameStatus.NEEDS_REVIEW : FrameStatus.SUCCESS,
                `Frame ${frameNumber}: ${frameShapes.length} object(s) created`,
            );
        }

        if (pendingSaves.length >= SAVE_BATCH_SIZE) {
            try {
                await flushSaves();
            } catch (err: unknown) {
                const msg = err instanceof Error ? err.message : String(err);
                onSaveProgress(`Warning: batch save failed: ${msg}`);
            }
        }
    }

    try {
        await flushSaves();
    } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        onSaveProgress(`Warning: final save failed: ${msg}`);
    }

    return {
        processed: frameResults.filter((r, idx, arr) => arr.findIndex((x) => x.frame === r.frame) === idx).length,
        successful,
        skipped,
        failed,
        needsReview,
        objectsCreated,
        frameResults,
    };
}
