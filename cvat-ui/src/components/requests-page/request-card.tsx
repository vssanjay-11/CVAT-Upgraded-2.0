// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React from 'react';
import { Link } from 'react-router-dom';
import dayjs from 'dayjs';

import { Row, Col } from 'antd/lib/grid';
import Card from 'antd/lib/card';
import Text from 'antd/lib/typography/Text';
import Progress from 'antd/lib/progress';
import { MoreOutlined } from '@ant-design/icons';
import Button from 'antd/lib/button';
import Checkbox from 'antd/lib/checkbox';
import { MenuProps } from 'antd/lib/menu';
import { BaseType } from 'antd/lib/typography/Base';

import { useDispatch } from 'react-redux';
import { RQStatus, Request, RequestOperation } from 'cvat-core-wrapper';
import { useContextMenuClick } from 'utils/hooks';
import { selectionActions } from 'actions/selection-actions';
import { SelectedResourceType } from 'reducers';

import StatusMessage from './request-status';
import RequestActionsComponent from './actions-menu';

const defaultOperation: RequestOperation = {
    target: '',
    type: '',
    format: null,
    jobID: null,
    taskID: null,
    projectID: null,
    functionID: null,
    lightweight: null,
};

export interface Props {
    request: Request;
    cancelled: boolean;
    selected?: boolean;
    onClick?: (event?: React.MouseEvent) => void;
}

function constructLink(request: Request): string | null {
    const op = request?.operation;
    if (!op) return null;
    const {
        type = '', target = '', jobID, taskID, projectID,
    } = op;

    if (request.status === RQStatus.FAILED && type?.includes('create')) {
        return null;
    }

    if (target === 'project' && projectID) {
        return `/projects/${projectID}`;
    }
    if (target === 'task' && taskID) {
        return `/tasks/${taskID}`;
    }
    if (target === 'job' && jobID) {
        return `/tasks/${taskID}/jobs/${jobID}`;
    }
    return null;
}

function constructName(operation?: Request['operation']): string | null {
    if (!operation) return null;
    const {
        target = '', jobID, taskID, projectID,
    } = operation;

    if (target === 'project' && projectID) {
        return `Project #${projectID}`;
    }
    if (target === 'task' && taskID) {
        return `Task #${taskID}`;
    }
    if (target === 'job' && jobID) {
        return `Job #${jobID}`;
    }
    return null;
}

function constructTypeText(type?: string): string {
    if (!type) return 'Request';
    return type.split(':').map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ');
}

function renderEllipsisText(text: string, type?: BaseType): JSX.Element {
    return (
        <Text ellipsis={{ tooltip: text }} type={type}>
            {text}
        </Text>
    );
}

function constructTimestamps(request: Request): JSX.Element {
    const started = dayjs(request.startedDate).format('MMM Do YY, H:mm');
    const finished = dayjs(request.finishedDate).format('MMM Do YY, H:mm');
    const created = dayjs(request.createdDate).format('MMM Do YY, H:mm');
    const expired = dayjs(request.expiryDate).format('MMM Do YY, H:mm');
    const type = request?.operation?.type || '';
    const url = request.url;

    switch (request.status) {
        case RQStatus.FINISHED: {
            const exportToCloudStorage = type.includes('export') && !url;
            if (request.expiryDate && !type.includes('create') && !type.includes('import') && !exportToCloudStorage) {
                return (
                    <>
                        <Row>
                            {renderEllipsisText(`Started by ${request.owner?.username || 'User'} on ${started}`, 'secondary')}
                        </Row>
                        <Row>
                            <Text type='secondary'>{`Expires on ${expired}`}</Text>
                        </Row>
                    </>
                );
            }
            return (
                <>
                    <Row>
                        {renderEllipsisText(`Started by ${request.owner?.username || 'User'} on ${started}`, 'secondary')}
                    </Row>
                    <Row>
                        <Text type='secondary'>{`Finished on ${finished}`}</Text>
                    </Row>
                </>
            );
        }
        case RQStatus.FAILED: {
            return (request.startedDate ? (
                <Row>
                    {renderEllipsisText(`Started by ${request.owner?.username || 'User'} on ${started}`, 'secondary')}
                </Row>
            ) : (
                <Row>
                    {renderEllipsisText(`Enqueued by ${request.owner?.username || 'User'} on ${created}`, 'secondary')}
                </Row>
            ));
        }
        case RQStatus.STARTED: {
            return (
                <>
                    <Row>
                        {renderEllipsisText(`Enqueued by ${request.owner?.username || 'User'} on ${created}`, 'secondary')}
                    </Row>
                    <Row>
                        <Text type='secondary'>{`Started on ${started}`}</Text>
                    </Row>
                </>
            );
        }
        default: {
            return (
                <Row>
                    {renderEllipsisText(`Enqueued by ${request.owner?.username || 'User'} on ${created}`, 'secondary')}
                </Row>
            );
        }
    }
}

const dimensions = {
    xs: 6,
    sm: 6,
    md: 8,
    lg: 8,
    xl: 8,
    xxl: 7,
};

function RequestCard(props: Readonly<Props>): JSX.Element {
    const {
        request, cancelled, selected, onClick,
    } = props;
    const dispatch = useDispatch();
    const operation = request.operation || defaultOperation;
    const { itemRef, handleContextMenuClick, handleContextMenuCapture } = useContextMenuClick<HTMLDivElement>();
    const type = operation.type || '';

    const linkToEntity = constructLink(request);
    const percent = request.status === RQStatus.FINISHED ? 100 : (request.progress ?? 0) * 100;
    const timestamps = constructTimestamps(request);
    const typeText = constructTypeText(type);

    const name = constructName(operation);

    const percentProgress = (request.status === RQStatus.FAILED || !percent) ? '' : `${percent.toFixed(2)}%`;

    const style: React.CSSProperties = {};
    if (cancelled) {
        style.pointerEvents = 'none';
        style.opacity = 0.5;
    }

    const card = (menuItems: NonNullable<MenuProps['items']>): JSX.Element => (
        <Card
            ref={itemRef}
            className={`cvat-requests-card${selected ? ' cvat-item-selected' : ''}`}
            style={style}
            onClick={(e) => {
                const target = e.target as HTMLElement | null;
                if (target?.closest?.('a, button, .ant-btn, .ant-dropdown, .ant-dropdown-trigger, .cvat-actions-menu-button, .ant-checkbox-wrapper')) {
                    return;
                }
                if (e.shiftKey) {
                    onClick?.(e);
                    return;
                }
                if (selected) {
                    dispatch(selectionActions.deselectResources([request.id], SelectedResourceType.REQUESTS));
                } else {
                    dispatch(selectionActions.selectResources([request.id], SelectedResourceType.REQUESTS));
                }
            }}
            onContextMenuCapture={handleContextMenuCapture}
        >
            <Row justify='space-between' align='middle' wrap={false}>
                <Col flex='36px' style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-start' }}>
                    <Checkbox
                        checked={selected}
                        onChange={(e) => {
                            e.stopPropagation();
                            if (selected) {
                                dispatch(selectionActions.deselectResources([request.id], SelectedResourceType.REQUESTS));
                            } else {
                                dispatch(selectionActions.selectResources([request.id], SelectedResourceType.REQUESTS));
                            }
                        }}
                        onClick={(e) => {
                            e.stopPropagation();
                        }}
                    />
                </Col>
                <Col flex='auto'>
                    <Row justify='space-between'>
                        <Col span={12}>
                            <Row style={{ paddingBottom: [RQStatus.FAILED].includes(request.status) ? '10px' : '0' }} gutter={8}>
                                <Col className='cvat-requests-type' {...dimensions}>
                                    {renderEllipsisText(typeText)}
                                </Col>
                                {name && (
                                    <Col className='cvat-requests-name'>
                                        {linkToEntity ?
                                            (<Link to={linkToEntity}>{name}</Link>) :
                                            <Text>{name}</Text>}
                                    </Col>
                                )}
                            </Row>
                            {timestamps}
                        </Col>
                        <Col span={10} className='cvat-request-item-progress-wrapper'>
                            <Row>
                                <Col span={21}>
                                    <Row />
                                    <StatusMessage
                                        message={request.message}
                                        status={request.status}
                                        cancelled={cancelled}
                                    />
                                    <Row>
                                        <Col span={18} className='cvat-requests-progress'>
                                            {request.status !== RQStatus.FAILED && (
                                                <Progress
                                                    percent={percent}
                                                    strokeColor={{
                                                        from: '#108ee9',
                                                        to: '#87d068',
                                                    }}
                                                    showInfo={false}
                                                    strokeWidth={5}
                                                    size='small'
                                                />
                                            )}
                                        </Col>
                                        <Col span={2} className='cvat-requests-percent'>
                                            {percentProgress}
                                        </Col>
                                    </Row>
                                    {operation?.format && (
                                        <Row>
                                            <Col className='cvat-format-name'>
                                                {renderEllipsisText(operation.format, 'secondary')}
                                            </Col>
                                        </Row>
                                    )}
                                    {operation?.lightweight && (
                                        <Row>
                                            <Col className='cvat-lightweight-label'>
                                                <Text type='secondary'>Lightweight backup</Text>
                                            </Col>
                                        </Row>
                                    )}
                                </Col>
                                <Col span={3} style={{ display: 'flex', justifyContent: 'end' }}>
                                    {menuItems.length > 0 && (
                                        <Button
                                            type='link'
                                            size='middle'
                                            className='cvat-requests-page-actions-button cvat-actions-menu-button'
                                            icon={<MoreOutlined className='cvat-menu-icon' />}
                                            onClick={handleContextMenuClick}
                                        />
                                    )}
                                </Col>
                            </Row>
                        </Col>
                    </Row>
                </Col>
            </Row>
        </Card>
    );

    return (
        <RequestActionsComponent
            requestInstance={request}
            dropdownTrigger={['contextMenu']}
            triggerElement={card}
        />
    );
}

export default React.memo(RequestCard);
