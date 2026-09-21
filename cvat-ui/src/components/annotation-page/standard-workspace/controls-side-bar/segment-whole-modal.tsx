// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useState, useRef, useEffect } from 'react';
import Modal from 'antd/lib/modal';
import Button from 'antd/lib/button';
import { Row, Col } from 'antd/lib/grid';
import Select from 'antd/lib/select';
import InputNumber from 'antd/lib/input-number';
import Input from 'antd/lib/input';
import Progress from 'antd/lib/progress';
import Alert from 'antd/lib/alert';
import Typography from 'antd/lib/typography';
import Divider from 'antd/lib/divider';
import Table from 'antd/lib/table';
import Space from 'antd/lib/space';
import Tag from 'antd/lib/tag';
import Slider from 'antd/lib/slider';
import Radio from 'antd/lib/radio';
import {
    PlayCircleOutlined,
    PauseCircleOutlined,
    StopOutlined,
    PlusOutlined,
    DeleteOutlined,
    CheckCircleOutlined,
    WarningOutlined,
    CloseCircleOutlined,
} from '@ant-design/icons';

import {
    Job, Label, MLModel, ShapeType,
    FrameStatus, runDenseSegmentWhole,
} from 'cvat-core-wrapper';
import type { DenseSegmentRunConfig, FrameResult } from 'cvat-core-wrapper';
import { DenseSegmentSettingsState } from 'reducers';
import openCVWrapper from 'utils/opencv-wrapper/opencv-wrapper';

const { Text, Title } = Typography;

interface LabelMappingRule {
    key: string;
    pattern: string;
    labelId: number;
}

export interface FrameRangeRuleUI {
    key: string;
    from: number;
    to: number;
    labelId: number;
}

interface Props {
    visible: boolean;
    jobInstance: Job;
    labels: Label[];
    interactors: MLModel[];
    denseSettings: DenseSegmentSettingsState;
    onClose: () => void;
    onFetchAnnotations: () => void;
    onUpdateSettings: (settings: Partial<DenseSegmentSettingsState>) => void;
}

export default function SegmentWholeModal(props: Props): JSX.Element {
    const {
        visible,
        jobInstance,
        labels,
        interactors,
        denseSettings,
        onClose,
        onFetchAnnotations,
        onUpdateSettings,
    } = props;

    // Config state
    const [modelId, setModelId] = useState<string>(String(denseSettings.lastModelId || interactors[0]?.id || ''));

    // Label Mode: 'auto' (Model-driven detection) | 'ranges' (custom frame ranges) | 'single' (all frames) | 'regex' (filename patterns)
    const [labelMode, setLabelMode] = useState<'auto' | 'ranges' | 'single' | 'regex'>(() => {
        try {
            const saved = localStorage.getItem('dense_segment_label_mode');
            if (saved === 'auto' || saved === 'ranges' || saved === 'single' || saved === 'regex') return saved;
        } catch { /* ignore */ }
        return 'auto';
    });

    const [singleLabelId, setSingleLabelId] = useState<number>(labels[0]?.id ?? 0);
    const [frameIndexMode, setFrameIndexMode] = useState<'one_based' | 'zero_based'>('one_based');
    const [fallbackLabelId, setFallbackLabelId] = useState<number>(0);

    const [maxSpacing, setMaxSpacing] = useState<number>(denseSettings.maxVertexSpacing ?? 2);
    const [minVertices, setMinVertices] = useState<number>(denseSettings.minVertices ?? 100);
    const [maxVertices, setMaxVertices] = useState<number>(denseSettings.maxVertices ?? 5000);
    const [maxAreaMismatch, setMaxAreaMismatch] = useState<number>((denseSettings.maxAreaMismatch ?? 0.05) * 100);
    const [batchBehavior, setBatchBehavior] = useState<'append' | 'replace_matching' | 'replace_all'>(
        denseSettings.batchBehavior ?? 'replace_matching',
    );
    const [confidenceThreshold, setConfidenceThreshold] = useState<number>(denseSettings.confidenceThreshold ?? 0.5);

    // Frame range rules with user defaults (e.g. 1 to 250 -> label 1, 500 to 750 -> label 2)
    const [frameRanges, setFrameRanges] = useState<FrameRangeRuleUI[]>(() => {
        try {
            const saved = localStorage.getItem('dense_segment_frame_ranges');
            if (saved) return JSON.parse(saved) as FrameRangeRuleUI[];
        } catch { /* ignore */ }
        const firstLabel = labels[0]?.id ?? 0;
        const secondLabel = labels[1]?.id ?? firstLabel;
        return [
            { key: 'range_1', from: 1, to: 250, labelId: firstLabel },
            { key: 'range_2', from: 500, to: 750, labelId: secondLabel },
        ];
    });

    // Label mapping rules (regex)
    const [mappings, setMappings] = useState<LabelMappingRule[]>(() => {
        try {
            const saved = localStorage.getItem('dense_segment_label_mappings');
            if (saved) return JSON.parse(saved) as LabelMappingRule[];
        } catch { /* ignore */ }
        return [];
    });

    // Execution state
    const [isRunning, setIsRunning] = useState<boolean>(false);
    const [isPaused, setIsPaused] = useState<boolean>(false);
    const [progress, setProgress] = useState<{
        frameIdx: number;
        totalFrames: number;
        status: FrameStatus;
        message: string;
    } | null>(null);
    const [saveNotice, setSaveNotice] = useState<string | null>(null);
    const [summary, setSummary] = useState<{
        processed: number;
        successful: number;
        skipped: number;
        failed: number;
        needsReview: number;
        frameResults: FrameResult[];
    } | null>(null);
    const [errorMessage, setErrorMessage] = useState<string | null>(null);

    // References for flow control
    const cancelledRef = useRef<boolean>(false);
    const isPausedRef = useRef<boolean>(false);
    isPausedRef.current = isPaused;

    // Persist mapping and range changes
    useEffect(() => {
        try {
            localStorage.setItem('dense_segment_label_mode', labelMode);
            localStorage.setItem('dense_segment_frame_ranges', JSON.stringify(frameRanges));
            localStorage.setItem('dense_segment_label_mappings', JSON.stringify(mappings));
        } catch { /* ignore */ }
    }, [labelMode, frameRanges, mappings]);

    // Handle frame range rules
    const handleAddRange = (): void => {
        const lastRange = frameRanges[frameRanges.length - 1];
        const nextFrom = lastRange ? Number(lastRange.to) + 1 : 1;
        const nextTo = nextFrom + 249;
        const nextLabel = labels[frameRanges.length % labels.length]?.id ?? (labels[0]?.id ?? 0);
        setFrameRanges([
            ...frameRanges,
            { key: `range_${Date.now()}`, from: nextFrom, to: nextTo, labelId: nextLabel },
        ]);
    };

    const handleRemoveRange = (key: string): void => {
        setFrameRanges(frameRanges.filter((r) => r.key !== key));
    };

    const handleUpdateRange = (key: string, field: 'from' | 'to' | 'labelId', val: number): void => {
        setFrameRanges(frameRanges.map((r) => {
            if (r.key === key) {
                return { ...r, [field]: val };
            }
            return r;
        }));
    };

    // Handle add mapping (regex)
    const handleAddMapping = (): void => {
        const newKey = `rule_${Date.now()}`;
        setMappings([
            ...mappings,
            { key: newKey, pattern: '', labelId: labels[0]?.id ?? 0 },
        ]);
    };

    // Handle remove mapping
    const handleRemoveMapping = (key: string): void => {
        setMappings(mappings.filter((m) => m.key !== key));
    };

    // Handle update mapping
    const handleUpdateMapping = (key: string, field: 'pattern' | 'labelId', val: string | number): void => {
        setMappings(mappings.map((m) => {
            if (m.key === key) {
                return { ...m, [field]: val };
            }
            return m;
        }));
    };

    // Pause helper
    const checkPause = async (): Promise<void> => {
        while (isPausedRef.current && !cancelledRef.current) {
            await new Promise((resolve) => setTimeout(resolve, 300));
        }
    };

    // Start Batch Job
    const handleStart = async (): Promise<void> => {
        setIsRunning(true);
        setIsPaused(false);
        cancelledRef.current = false;
        setProgress(null);
        setSummary(null);
        setErrorMessage(null);
        setSaveNotice(null);

        // Update settings in store
        onUpdateSettings({
            maxVertexSpacing: maxSpacing,
            minVertices,
            maxVertices,
            maxAreaMismatch: maxAreaMismatch / 100,
            batchBehavior,
            confidenceThreshold,
            lastModelId: modelId,
        });

        // Initialize OpenCV if needed
        try {
            if (!openCVWrapper.isInitialized) {
                setSaveNotice('Initializing OpenCV contour utilities...');
                await openCVWrapper.initialize(() => {});
            }
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            setErrorMessage(`Failed to initialize OpenCV: ${msg}`);
            setIsRunning(false);
            return;
        }

        const runConfig: DenseSegmentRunConfig = {
            modelId,
            labelId: labelMode === 'single' ? singleLabelId : 0,
            maxSpacing,
            minVertices,
            maxVertices,
            maxAreaMismatch: maxAreaMismatch / 100,
            batchBehavior,
            labelMappingsJson: labelMode === 'regex' ? JSON.stringify(mappings.map(({ pattern, labelId: mappedLabelId }) => ({
                pattern,
                labelId: mappedLabelId,
            }))) : '',
            frameRangeRulesJson: labelMode === 'ranges' ? JSON.stringify(frameRanges.map(({ from, to, labelId: rLabelId }) => ({
                from,
                to,
                labelId: rLabelId,
            }))) : undefined,
            frameRangeIndexMode: frameIndexMode,
            fallbackLabelId: labelMode === 'ranges' ? fallbackLabelId : 0,
            confidenceThreshold,
        };

        const getContours = (mask: Int32Array): [number, number][][] => (
            openCVWrapper.getContoursFromStateSync({
                points: mask,
                shapeType: ShapeType.MASK,
            })
        );

        try {
            const result = await runDenseSegmentWhole(
                jobInstance,
                runConfig,
                getContours,
                (frameIdx, totalFrames, status, message) => {
                    setProgress({ frameIdx, totalFrames, status, message });
                    void checkPause();
                },
                (notice) => setSaveNotice(notice),
                () => cancelledRef.current,
            );

            setSummary(result);
            onFetchAnnotations();
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            setErrorMessage(`Segment Whole execution error: ${msg}`);
        } finally {
            setIsRunning(false);
            setSaveNotice(null);
        }
    };

    const handleCancel = (): void => {
        cancelledRef.current = true;
        setIsPaused(false);
    };

    const handleTogglePause = (): void => {
        setIsPaused(!isPaused);
    };

    // Columns for frame range mapping table
    const rangeColumns = [
        {
            title: 'From Frame',
            dataIndex: 'from',
            key: 'from',
            width: 130,
            render: (fromVal: number, record: FrameRangeRuleUI) => (
                <InputNumber
                    min={frameIndexMode === 'zero_based' ? 0 : 1}
                    value={fromVal}
                    disabled={isRunning}
                    style={{ width: '100%' }}
                    onChange={(val) => handleUpdateRange(record.key, 'from', val ?? (frameIndexMode === 'zero_based' ? 0 : 1))}
                />
            ),
        },
        {
            title: 'To Frame',
            dataIndex: 'to',
            key: 'to',
            width: 130,
            render: (toVal: number, record: FrameRangeRuleUI) => (
                <InputNumber
                    min={record.from}
                    value={toVal}
                    disabled={isRunning}
                    style={{ width: '100%' }}
                    onChange={(val) => handleUpdateRange(record.key, 'to', val ?? record.from)}
                />
            ),
        },
        {
            title: 'Target Label',
            dataIndex: 'labelId',
            key: 'labelId',
            render: (curLabelId: number, record: FrameRangeRuleUI) => (
                <Select
                    style={{ width: '100%' }}
                    value={curLabelId}
                    disabled={isRunning}
                    onChange={(val: number) => handleUpdateRange(record.key, 'labelId', val)}
                >
                    {labels.map((lbl) => (
                        <Select.Option key={lbl.id} value={lbl.id}>
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                                <span style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: lbl.color || '#1890ff', display: 'inline-block' }} />
                                {lbl.name}
                            </span>
                        </Select.Option>
                    ))}
                </Select>
            ),
        },
        {
            title: 'Action',
            key: 'action',
            width: 70,
            render: (_: unknown, record: FrameRangeRuleUI) => (
                <Button
                    type='text'
                    danger
                    icon={<DeleteOutlined />}
                    disabled={isRunning || frameRanges.length <= 1}
                    onClick={() => handleRemoveRange(record.key)}
                />
            ),
        },
    ];

    // Columns for label mapping table (regex)
    const mappingColumns = [
        {
            title: 'Filename Regex Pattern',
            dataIndex: 'pattern',
            key: 'pattern',
            render: (text: string, record: LabelMappingRule) => (
                <Input
                    placeholder='e.g. .*weld.* or part_[0-9]+'
                    value={text}
                    disabled={isRunning}
                    onChange={(e) => handleUpdateMapping(record.key, 'pattern', e.target.value)}
                />
            ),
        },
        {
            title: 'Target Label',
            dataIndex: 'labelId',
            key: 'labelId',
            render: (currentLabelId: number, record: LabelMappingRule) => (
                <Select
                    style={{ width: '100%' }}
                    value={currentLabelId}
                    disabled={isRunning}
                    onChange={(val: number) => handleUpdateMapping(record.key, 'labelId', val)}
                >
                    {labels.map((lbl) => (
                        <Select.Option key={lbl.id} value={lbl.id}>
                            {lbl.name}
                        </Select.Option>
                    ))}
                </Select>
            ),
        },
        {
            title: 'Action',
            key: 'action',
            width: 80,
            render: (_: unknown, record: LabelMappingRule) => (
                <Button
                    type='text'
                    danger
                    icon={<DeleteOutlined />}
                    disabled={isRunning}
                    onClick={() => handleRemoveMapping(record.key)}
                />
            ),
        },
    ];

    // Results table columns for summary view
    const resultsColumns = [
        {
            title: 'Frame',
            dataIndex: 'frame',
            key: 'frame',
            width: 90,
        },
        {
            title: 'Status',
            dataIndex: 'status',
            key: 'status',
            width: 130,
            render: (status: FrameStatus) => {
                if (status === FrameStatus.SUCCESS) return <Tag color='success'>Success</Tag>;
                if (status === FrameStatus.NEEDS_REVIEW) return <Tag color='warning'>Needs Review</Tag>;
                if (status === FrameStatus.SKIPPED) return <Tag color='default'>Skipped</Tag>;
                return <Tag color='error'>Failed</Tag>;
            },
        },
        {
            title: 'Vertices',
            dataIndex: 'vertexCount',
            key: 'vertexCount',
            width: 100,
            render: (v: number | undefined) => (v !== undefined ? v : '—'),
        },
        {
            title: 'Details',
            dataIndex: 'reason',
            key: 'reason',
            render: (r: string | undefined) => (
                <Text type={r?.includes('mismatch') ? 'warning' : 'secondary'}>
                    {r || 'OK'}
                </Text>
            ),
        },
    ];

    return (
        <Modal
            title='Segment Whole — Batch Dense Segmentation'
            open={visible}
            onCancel={isRunning ? undefined : onClose}
            footer={null}
            width={840}
            zIndex={1500}
            destroyOnClose={false}
            maskClosable={!isRunning}
            closable={!isRunning}
        >
            <div style={{ maxHeight: '72vh', overflowY: 'auto', paddingRight: '8px' }}>
                {errorMessage && (
                    <Alert
                        type='error'
                        message={errorMessage}
                        showIcon
                        closable
                        onClose={() => setErrorMessage(null)}
                        style={{ marginBottom: '16px' }}
                    />
                )}

                {/* Progress Panel */}
                {isRunning && progress && (
                    <div style={{ marginBottom: '20px', padding: '16px', background: '#f5f5f5', borderRadius: '8px' }}>
                        <Row justify='space-between' align='middle'>
                            <Col>
                                <Text strong>
                                    Processing Frame {progress.frameIdx + 1} of {progress.totalFrames}
                                </Text>
                            </Col>
                            <Col>
                                <Space>
                                    <Button
                                        icon={isPaused ? <PlayCircleOutlined /> : <PauseCircleOutlined />}
                                        onClick={handleTogglePause}
                                    >
                                        {isPaused ? 'Resume' : 'Pause'}
                                    </Button>
                                    <Button
                                        danger
                                        icon={<StopOutlined />}
                                        onClick={handleCancel}
                                    >
                                        Cancel
                                    </Button>
                                </Space>
                            </Col>
                        </Row>
                        <Progress
                            percent={Math.round(((progress.frameIdx + 1) / progress.totalFrames) * 100)}
                            status={isPaused ? 'normal' : 'active'}
                            style={{ margin: '12px 0' }}
                        />
                        <Text type='secondary'>{progress.message}</Text>
                        {saveNotice && (
                            <div style={{ marginTop: '6px' }}>
                                <Text type='warning'>{saveNotice}</Text>
                            </div>
                        )}
                    </div>
                )}

                {/* Summary Panel */}
                {summary && !isRunning && (
                    <div style={{ marginBottom: '20px', padding: '16px', background: '#fafafa', borderRadius: '8px', border: '1px solid #d9d9d9' }}>
                        <Title level={5}>
                            <CheckCircleOutlined style={{ color: '#52c41a', marginRight: '8px' }} />
                            Batch Segmentation Complete
                        </Title>
                        <Row gutter={[16, 8]} style={{ marginBottom: '16px' }}>
                            <Col span={5}>
                                <Text type='secondary'>Total Processed:</Text>
                                <br />
                                <Text strong style={{ fontSize: '18px' }}>{summary.processed}</Text>
                            </Col>
                            <Col span={5}>
                                <Text type='secondary'>Successful:</Text>
                                <br />
                                <Text strong style={{ fontSize: '18px', color: '#52c41a' }}>{summary.successful}</Text>
                            </Col>
                            <Col span={5}>
                                <Text type='secondary'>Needs Review:</Text>
                                <br />
                                <Text strong style={{ fontSize: '18px', color: '#faad14' }}>{summary.needsReview}</Text>
                            </Col>
                            <Col span={5}>
                                <Text type='secondary'>Skipped:</Text>
                                <br />
                                <Text strong style={{ fontSize: '18px', color: '#8c8c8c' }}>{summary.skipped}</Text>
                            </Col>
                            <Col span={4}>
                                <Text type='secondary'>Failed:</Text>
                                <br />
                                <Text strong style={{ fontSize: '18px', color: '#ff4d4f' }}>{summary.failed}</Text>
                            </Col>
                        </Row>

                        <Divider style={{ margin: '12px 0' }} />
                        <Text strong>Frame Results Details</Text>
                        <Table
                            size='small'
                            dataSource={summary.frameResults.map((r) => ({ ...r, key: `fr_${r.frame}` }))}
                            columns={resultsColumns}
                            pagination={{ pageSize: 5 }}
                            style={{ marginTop: '8px' }}
                        />
                    </div>
                )}

                {/* Configuration Panel */}
                <fieldset disabled={isRunning} style={{ border: 'none', padding: 0, margin: 0 }}>
                    <Row gutter={[16, 12]}>
                        <Col span={10}>
                            <div>
                                <Text strong>AI Interactor Model</Text>
                            </div>
                            <Select
                                style={{ width: '100%', marginTop: '4px' }}
                                value={modelId}
                                onChange={(val: string) => setModelId(val)}
                            >
                                {interactors.map((m) => (
                                    <Select.Option key={m.id} value={m.id}>
                                        {m.name}
                                    </Select.Option>
                                ))}
                            </Select>
                        </Col>

                        <Col span={14}>
                            <div>
                                <Text strong>Label Assignment Strategy</Text>
                            </div>
                            <Radio.Group
                                value={labelMode}
                                onChange={(e) => setLabelMode(e.target.value)}
                                style={{ marginTop: '4px' }}
                                buttonStyle='solid'
                            >
                                <Radio.Button value='auto'>Model Detection (Auto)</Radio.Button>
                                <Radio.Button value='ranges'>Frame Ranges</Radio.Button>
                                <Radio.Button value='single'>Single Label</Radio.Button>
                                <Radio.Button value='regex'>Regex Filename</Radio.Button>
                            </Radio.Group>
                        </Col>
                    </Row>

                    {labelMode === 'auto' && (
                        <div style={{ marginTop: '12px', padding: '10px 12px', background: '#f6ffed', border: '1px solid #b7eb8f', borderRadius: '6px' }}>
                            <Text strong style={{ color: '#389e0d' }}>Automatic Model-Driven Labeling Active</Text>
                            <Text type='secondary' style={{ display: 'block', fontSize: '12px', marginTop: '2px' }}>
                                The YOLO11s-seg model dynamically classifies each detected physical component (TRANSMISSION HOUSING or PLV BODY) and assigns its matching CVAT task label per instance.
                            </Text>
                        </div>
                    )}

                    {labelMode === 'single' && (
                        <div style={{ marginTop: '12px' }}>
                            <Text strong>Target Label (Applied to All Frames)</Text>
                            <Select
                                style={{ width: '100%', marginTop: '4px' }}
                                value={singleLabelId}
                                onChange={(val: number) => setSingleLabelId(val)}
                            >
                                {labels.map((lbl) => (
                                    <Select.Option key={lbl.id} value={lbl.id}>
                                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}>
                                            <span style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: lbl.color || '#1890ff', display: 'inline-block' }} />
                                            {lbl.name}
                                        </span>
                                    </Select.Option>
                                ))}
                            </Select>
                        </div>
                    )}

                    {labelMode === 'ranges' && (
                        <div style={{ marginTop: '14px', padding: '12px', background: '#fafafa', border: '1px solid #e8e8e8', borderRadius: '6px' }}>
                            <Row justify='space-between' align='middle' style={{ marginBottom: '8px' }}>
                                <Col>
                                    <Text strong>Custom Frame Ranges Mapping</Text>
                                    <Text type='secondary' style={{ display: 'block', fontSize: '12px' }}>
                                        Specify frame ranges and their assigned labels (e.g. 1 to 250 &rarr; PLV BODY, 500 to 750 &rarr; TRANSMISSION HOUSING).
                                    </Text>
                                </Col>
                                <Col>
                                    <Space>
                                        <Text type='secondary' style={{ fontSize: '12px' }}>Frame Numbering:</Text>
                                        <Select
                                            size='small'
                                            value={frameIndexMode}
                                            onChange={(val) => setFrameIndexMode(val)}
                                            style={{ width: 165 }}
                                        >
                                            <Select.Option value='one_based'>1-based (Frame 1 = #1)</Select.Option>
                                            <Select.Option value='zero_based'>0-based (Frame 0 = #1)</Select.Option>
                                        </Select>
                                    </Space>
                                </Col>
                            </Row>

                            <Table
                                size='small'
                                columns={rangeColumns}
                                dataSource={frameRanges}
                                pagination={false}
                                style={{ marginBottom: '8px' }}
                                locale={{ emptyText: 'No frame ranges specified. Click "+ Add Frame Range" below.' }}
                            />

                            <Row justify='space-between' align='middle' style={{ marginTop: '8px' }}>
                                <Col>
                                    <Button
                                        type='dashed'
                                        icon={<PlusOutlined />}
                                        onClick={handleAddRange}
                                        disabled={isRunning}
                                    >
                                        Add Frame Range
                                    </Button>
                                </Col>
                                <Col>
                                    <Space align='center'>
                                        <Text type='secondary' style={{ fontSize: '12px' }}>Frames Outside Ranges:</Text>
                                        <Select
                                            size='small'
                                            value={fallbackLabelId}
                                            onChange={(val: number) => setFallbackLabelId(val)}
                                            style={{ width: 170 }}
                                        >
                                            <Select.Option value={0}>
                                                <em>Skip unlisted frames</em>
                                            </Select.Option>
                                            {labels.map((lbl) => (
                                                <Select.Option key={lbl.id} value={lbl.id}>
                                                    Use {lbl.name}
                                                </Select.Option>
                                            ))}
                                        </Select>
                                    </Space>
                                </Col>
                            </Row>
                        </div>
                    )}

                    {labelMode === 'regex' && (
                        <div style={{ marginTop: '14px', padding: '12px', background: '#fafafa', border: '1px solid #e8e8e8', borderRadius: '6px' }}>
                            <Text strong>Filename Regex Label Mappings</Text>
                            <Text type='secondary' style={{ fontSize: '12px', display: 'block', marginBottom: '8px' }}>
                                When &quot;Regex Filename&quot; is selected, each frame&apos;s filename is tested against these patterns.
                                The first matching pattern assigns the corresponding label. Unmatched frames are skipped.
                            </Text>
                            <Table
                                size='small'
                                columns={mappingColumns}
                                dataSource={mappings}
                                pagination={false}
                                locale={{ emptyText: 'No rules added. Click "Add Mapping Rule" below.' }}
                            />
                            <Button
                                type='dashed'
                                icon={<PlusOutlined />}
                                onClick={handleAddMapping}
                                disabled={isRunning}
                                style={{ width: '100%', marginTop: '8px' }}
                            >
                                Add Mapping Rule
                            </Button>
                        </div>
                    )}

                    <Divider style={{ margin: '16px 0 12px 0' }}>Density Parameters</Divider>

                    <Row gutter={[16, 12]}>
                        <Col span={6}>
                            <Text>Max Vertex Spacing</Text>
                            <InputNumber
                                min={0.5}
                                max={50}
                                step={0.5}
                                value={maxSpacing}
                                onChange={(val) => setMaxSpacing(val || 2)}
                                addonAfter='px'
                                style={{ width: '100%', marginTop: '4px' }}
                            />
                        </Col>
                        <Col span={6}>
                            <Text>Min Vertices</Text>
                            <InputNumber
                                min={3}
                                max={1000}
                                value={minVertices}
                                onChange={(val) => setMinVertices(val || 100)}
                                style={{ width: '100%', marginTop: '4px' }}
                            />
                        </Col>
                        <Col span={6}>
                            <Text>Max Vertices</Text>
                            <InputNumber
                                min={100}
                                max={100000}
                                value={maxVertices}
                                onChange={(val) => setMaxVertices(val || 5000)}
                                style={{ width: '100%', marginTop: '4px' }}
                            />
                        </Col>
                        <Col span={6}>
                            <Text>Max Area Mismatch</Text>
                            <InputNumber
                                min={1}
                                max={50}
                                step={1}
                                value={maxAreaMismatch}
                                onChange={(val) => setMaxAreaMismatch(val || 5)}
                                addonAfter='%'
                                style={{ width: '100%', marginTop: '4px' }}
                            />
                        </Col>
                    </Row>

                    <Row gutter={[16, 12]} style={{ marginTop: '12px' }}>
                        <Col span={12}>
                            <Text>Batch Behavior (Existing Annotations)</Text>
                            <Select
                                style={{ width: '100%', marginTop: '4px' }}
                                value={batchBehavior}
                                onChange={(val) => setBatchBehavior(val)}
                            >
                                <Select.Option value='append'>Append (Keep all existing annotations)</Select.Option>
                                <Select.Option value='replace_matching'>Replace matching labels</Select.Option>
                                <Select.Option value='replace_all'>Replace all annotations on frame</Select.Option>
                            </Select>
                        </Col>
                        <Col span={12}>
                            <Text>Confidence Threshold ({confidenceThreshold})</Text>
                            <Slider
                                min={0.1}
                                max={1.0}
                                step={0.05}
                                value={confidenceThreshold}
                                onChange={(val: number) => setConfidenceThreshold(val)}
                                style={{ marginTop: '8px' }}
                            />
                        </Col>
                    </Row>
                </fieldset>
            </div>

            <Divider style={{ margin: '16px 0' }} />

            <Row justify='end'>
                <Space>
                    <Button onClick={onClose} disabled={isRunning}>
                        {summary ? 'Close' : 'Cancel'}
                    </Button>
                    <Button
                        type='primary'
                        icon={<PlayCircleOutlined />}
                        loading={isRunning}
                        disabled={!modelId || interactors.length === 0}
                        onClick={handleStart}
                    >
                        {isRunning ? 'Processing...' : 'Start Segment Whole'}
                    </Button>
                </Space>
            </Row>
        </Modal>
    );
}
