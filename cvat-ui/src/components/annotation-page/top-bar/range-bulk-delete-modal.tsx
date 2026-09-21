// Copyright (C) CVAT.ai Corporation
// SPDX-License-Identifier: MIT

import React, { useEffect, useState, useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import Modal from 'antd/lib/modal';
import Text from 'antd/lib/typography/Text';
import InputNumber from 'antd/lib/input-number';
import Input from 'antd/lib/input';
import Checkbox from 'antd/lib/checkbox';
import Alert from 'antd/lib/alert';
import Spin from 'antd/lib/spin';
import Space from 'antd/lib/space';
import notification from 'antd/lib/notification';
import { Row, Col } from 'antd/lib/grid';
import { DeleteOutlined, ExclamationCircleOutlined } from '@ant-design/icons';

import { Job, getCore } from 'cvat-core-wrapper';
import { fetchAnnotationsAsync } from 'actions/annotation-actions';
import { CombinedState } from 'reducers';

const core = getCore();

export interface RangeBulkDeleteModalProps {
    open: boolean;
    onClose(): void;
}

interface PreviewStats {
    affectedFrames: number;
    affectedShapes: number;
    totalShapes: number;
    ranges: [number, number][];
}

export default function RangeBulkDeleteModal(props: RangeBulkDeleteModalProps): JSX.Element {
    const { open, onClose } = props;
    const dispatch = useDispatch();
    const jobInstance = useSelector((state: CombinedState) => state.annotation.job.instance as Job);
    const startFrame = jobInstance?.startFrame ?? 0;
    const stopFrame = jobInstance?.stopFrame ?? 0;

    const [rangeMode, setRangeMode] = useState<'single' | 'multi'>('single');
    const [startF, setStartF] = useState<number | null>(startFrame);
    const [endF, setEndF] = useState<number | null>(Math.min(startFrame + 50, stopFrame));
    const [multiRangeText, setMultiRangeText] = useState<string>('');

    const [loadingPreview, setLoadingPreview] = useState<boolean>(false);
    const [previewStats, setPreviewStats] = useState<PreviewStats | null>(null);
    const [previewError, setPreviewError] = useState<string | null>(null);

    const [confirmed, setConfirmed] = useState<boolean>(false);
    const [deleting, setDeleting] = useState<boolean>(false);

    // Build range payload
    const getRangePayload = useCallback(() => {
        if (rangeMode === 'single') {
            if (startF === null || endF === null) return null;
            return [{ from: Number(startF), to: Number(endF) }];
        }
        return multiRangeText.trim();
    }, [rangeMode, startF, endF, multiRangeText]);

    // Fetch affected counts from backend
    const fetchPreview = useCallback(async () => {
        if (!jobInstance) return;

        if (rangeMode === 'single') {
            if (startF === null || endF === null) {
                setPreviewStats(null);
                setPreviewError(null);
                return;
            }
            if (startF > endF) {
                setPreviewStats(null);
                setPreviewError(`Start Frame (${startF}) cannot be greater than End Frame (${endF})`);
                return;
            }
        }

        const payload = getRangePayload();
        if (!payload || (typeof payload === 'string' && !payload.trim())) {
            setPreviewStats(null);
            setPreviewError(null);
            return;
        }

        setLoadingPreview(true);
        setPreviewError(null);

        try {
            const res: any = await core.server.request(
                `${core.config.backendAPI}/jobs/${jobInstance.id}/annotations/bulk-delete/preview`,
                {
                    method: 'POST',
                    data: typeof payload === 'string' ? { range_str: payload } : { ranges: payload },
                },
            );

            const data = res?.data !== undefined ? res.data : res;

            const affectedFrames = Number(data?.affected_frames_count ?? 0);
            const affectedShapes = Number(data?.affected_shapes_count ?? 0);
            const totalShapes = Number(data?.total_shapes_count ?? 0);
            const ranges = data?.ranges || [];

            setPreviewStats({
                affectedFrames,
                affectedShapes,
                totalShapes,
                ranges,
            });
        } catch (err: any) {
            const errorMsg = err?.response?.data?.error || err?.message || 'Failed to calculate affected annotations';
            setPreviewError(errorMsg);
            setPreviewStats(null);
        } finally {
            setLoadingPreview(false);
        }
    }, [jobInstance, rangeMode, startF, endF, getRangePayload]);

    useEffect(() => {
        if (!open) return;
        setConfirmed(false);
        const timer = setTimeout(() => {
            fetchPreview();
        }, 150);
        return () => clearTimeout(timer);
    }, [open, fetchPreview]);

    const handleDelete = async () => {
        if (!jobInstance) return;
        const payload = getRangePayload();
        if (!payload) return;

        setDeleting(true);
        try {
            const res: any = await core.server.request(
                `${core.config.backendAPI}/jobs/${jobInstance.id}/annotations/bulk-delete`,
                {
                    method: 'POST',
                    data: typeof payload === 'string' ? { range_str: payload } : { ranges: payload },
                },
            );

            const data = res?.data !== undefined ? res.data : res;
            const deletedCount = Number(data?.deleted_count ?? 0);
            const affectedFramesCount = Number(data?.affected_frames_count ?? 0);

            notification.success({
                message: 'Bulk Deletion Complete',
                description: `Successfully deleted ${deletedCount} annotations across ${affectedFramesCount} frames.`,
                duration: 4,
            });

            // Refresh CVAT Core state and canvas without reload
            await jobInstance.annotations.clear({ reload: true });
            await jobInstance.actions.clear();
            dispatch(fetchAnnotationsAsync());

            onClose();
        } catch (err: any) {
            const errorMsg = err?.response?.data?.error || err?.message || 'Error occurred while deleting annotations';
            notification.error({
                message: 'Bulk Deletion Failed',
                description: errorMsg,
            });
        } finally {
            setDeleting(false);
        }
    };

    return (
        <Modal
            destroyOnClose
            open={open}
            title={
                <Space>
                    <DeleteOutlined style={{ color: '#ff4d4f' }} />
                    <Text strong style={{ fontSize: 16 }}>Bulk Delete Annotations</Text>
                </Space>
            }
            className='cvat-modal-bulk-delete-annotations'
            okText={
                deleting
                    ? 'Deleting...'
                    : previewStats && previewStats.affectedShapes > 0
                    ? `Delete ${previewStats.affectedShapes} Annotations`
                    : 'Delete Annotations'
            }
            okButtonProps={{
                type: 'primary',
                danger: true,
                disabled: !confirmed || !previewStats || previewStats.affectedShapes === 0 || deleting,
                loading: deleting,
            }}
            cancelButtonProps={{ disabled: deleting }}
            onCancel={onClose}
            onOk={handleDelete}
            width={520}
        >
            <div style={{ padding: '8px 0' }}>
                <Alert
                    type='warning'
                    showIcon
                    icon={<ExclamationCircleOutlined />}
                    message='Safe Annotation Deletion'
                    description='This will delete annotations only. Source images, task configuration, and labels will NOT be deleted.'
                    style={{ marginBottom: 16 }}
                />

                <div style={{ marginBottom: 12 }}>
                    <Text strong>Range Selection Mode:</Text>
                    <div style={{ marginTop: 6 }}>
                        <Space>
                            <Checkbox
                                checked={rangeMode === 'single'}
                                onChange={() => {
                                    setRangeMode('single');
                                }}
                            >
                                Single continuous range
                            </Checkbox>
                            <Checkbox
                                checked={rangeMode === 'multi'}
                                onChange={() => {
                                    setRangeMode('multi');
                                }}
                            >
                                Multiple ranges
                            </Checkbox>
                        </Space>
                    </div>
                </div>

                {rangeMode === 'single' ? (
                    <Row gutter={16} align='middle' style={{ marginBottom: 16 }}>
                        <Col span={12}>
                            <Text>Start Frame:</Text>
                            <InputNumber
                                min={startFrame}
                                max={stopFrame}
                                value={startF}
                                style={{ width: '100%', marginTop: 4 }}
                                onChange={(val) => {
                                    setStartF(val !== null && val !== undefined ? Number(val) : null);
                                }}
                            />
                        </Col>
                        <Col span={12}>
                            <Text>End Frame:</Text>
                            <InputNumber
                                min={startFrame}
                                max={stopFrame}
                                value={endF}
                                style={{ width: '100%', marginTop: 4 }}
                                onChange={(val) => {
                                    setEndF(val !== null && val !== undefined ? Number(val) : null);
                                }}
                            />
                        </Col>
                    </Row>
                ) : (
                    <div style={{ marginBottom: 16 }}>
                        <Text>Enter comma-separated frame ranges (e.g. 100-150, 200-240, 500-550):</Text>
                        <Input
                            placeholder='100-150, 200-240'
                            value={multiRangeText}
                            style={{ marginTop: 4 }}
                            onChange={(e) => setMultiRangeText(e.target.value)}
                        />
                    </div>
                )}

                {/* Preview Box */}
                <div
                    style={{
                        background: '#f5f5f5',
                        borderRadius: 6,
                        padding: 12,
                        marginBottom: 16,
                        border: '1px solid #e8e8e8',
                    }}
                >
                    {loadingPreview ? (
                        <div style={{ textAlign: 'center', padding: '8px 0' }}>
                            <Spin size='small' />
                            <Text style={{ marginLeft: 8 }} type='secondary'>Calculating affected annotations...</Text>
                        </div>
                    ) : previewError ? (
                        <Text type='danger'>{previewError}</Text>
                    ) : previewStats ? (
                        <div>
                            <Row justify='space-between' style={{ marginBottom: 4 }}>
                                <Text type='secondary'>Affected Frames:</Text>
                                <Text strong>{previewStats.affectedFrames}</Text>
                            </Row>
                            <Row justify='space-between' style={{ marginBottom: 4 }}>
                                <Text type='secondary'>Annotations to be deleted:</Text>
                                <Text strong style={{ color: previewStats.affectedShapes > 0 ? '#ff4d4f' : 'inherit' }}>
                                    {previewStats.affectedShapes}
                                </Text>
                            </Row>
                            <Row justify='space-between'>
                                <Text type='secondary'>Remaining annotations:</Text>
                                <Text strong>{Math.max(0, (previewStats.totalShapes || 0) - (previewStats.affectedShapes || 0))}</Text>
                            </Row>
                        </div>
                    ) : (
                        <Text type='secondary'>Enter a valid range to preview affected annotations.</Text>
                    )}
                </div>

                <Checkbox
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                    disabled={!previewStats || previewStats.affectedShapes === 0 || deleting}
                >
                    <Text strong>
                        {previewStats && previewStats.affectedShapes > 0
                            ? `I confirm deletion of ${previewStats.affectedShapes} annotations.`
                            : 'No annotations in this range to delete.'}
                    </Text>
                </Checkbox>
            </div>
        </Modal>
    );
}
