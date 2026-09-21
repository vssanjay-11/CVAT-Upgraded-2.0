// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { shallowEqual } from 'utils/redux';
import dayjs from 'dayjs';
import { CombinedState, RequestsQuery, SelectedResourceType } from 'reducers';

import { Row, Col } from 'antd/lib/grid';
import Pagination from 'antd/lib/pagination';
import Button from 'antd/lib/button';
import Modal from 'antd/lib/modal';
import { DeleteOutlined } from '@ant-design/icons';

import { Request, RQStatus } from 'cvat-core-wrapper';
import { requestsActions } from 'actions/requests-actions';
import { bulkDeleteRequestsAsync } from 'actions/requests-async-actions';

import dimensions from 'utils/dimensions';
import { ResourceSelectionInfo } from 'components/resource-sorting-filtering';
import BulkWrapper from 'components/bulk-wrapper';
import { selectionActions } from 'actions/selection-actions';
import RequestCard from './request-card';

interface Props {
    query: RequestsQuery;
    count: number;
}

function setUpRequestsList(requests: Request[], newPage: number, pageSize: number): Request[] {
    const displayRequests = [...requests];
    displayRequests.sort((a, b) => dayjs(b.createdDate).valueOf() - dayjs(a.createdDate).valueOf());
    return displayRequests.slice((newPage - 1) * pageSize, newPage * pageSize);
}

function RequestsList(props: Readonly<Props>): JSX.Element {
    const dispatch = useDispatch();
    const { query, count } = props;
    const { page, pageSize } = query;
    const { requests, cancelled, selectedCount, selectedIds } = useSelector((state: CombinedState) => ({
        requests: state.requests.requests,
        cancelled: state.requests.cancelled,
        selectedCount: state.requests.selected.length,
        selectedIds: state.requests.selected,
    }), shallowEqual);

    const requestList = Object.values(requests);
    const requestViews = setUpRequestsList(requestList, page, pageSize);
    const requestIds = requestViews
        .filter((request) => !(request.id in cancelled) && request.status !== RQStatus.CANCELED)
        .map((request) => request.id);
    const onSelectAll = useCallback(() => {
        dispatch(selectionActions.selectResources(requestIds, SelectedResourceType.REQUESTS));
    }, [requestIds, dispatch]);

    const onDeleteSelected = useCallback(() => {
        if (selectedIds.length === 0) return;

        Modal.confirm({
            title: `Delete ${selectedIds.length} ticked export(s)?`,
            content: 'The selected export records and their files will be permanently deleted from the local server exports folder. Continue?',
            className: 'cvat-modal-confirm-bulk-delete-requests',
            okText: 'Delete',
            okButtonProps: {
                type: 'primary',
                danger: true,
            },
            onOk: async () => {
                await dispatch(bulkDeleteRequestsAsync(selectedIds));
            },
        });
    }, [selectedIds, dispatch]);

    return (
        <>
            <Row justify='center'>
                <Col {...dimensions} style={{ display: 'flex', alignItems: 'center' }}>
                    <ResourceSelectionInfo selectedCount={selectedCount} onSelectAll={onSelectAll} />
                    {selectedCount > 0 && (
                        <Button
                            danger
                            type='primary'
                            size='small'
                            icon={<DeleteOutlined />}
                            style={{ marginLeft: 12, borderRadius: 4 }}
                            onClick={onDeleteSelected}
                        >
                            {selectedCount === requestIds.length ?
                                `Delete all (${selectedCount})` :
                                `Delete the ticked (${selectedCount})`}
                        </Button>
                    )}
                </Col>
            </Row>
            <Row justify='center' className='cvat-resource-list-wrapper'>
                <Col className='cvat-requests-list' {...dimensions}>
                    <BulkWrapper currentResourceIds={requestIds} resourceType={SelectedResourceType.REQUESTS}>
                        {(selectProps) => (
                            requestViews.map((request: Request) => {
                                const isCancelled = request.id in cancelled || request.status === RQStatus.CANCELED;
                                const selectableIndex = isCancelled ? -1 : requestIds.indexOf(request.id);
                                const canSelect = !isCancelled && selectableIndex !== -1;

                                const { selected, onClick } = canSelect ?
                                    selectProps(request.id, selectableIndex) :
                                    { selected: false, onClick: () => false };

                                return (
                                    <RequestCard
                                        request={request}
                                        key={request.id}
                                        cancelled={isCancelled}
                                        selected={selected}
                                        onClick={onClick}
                                    />
                                );
                            })
                        )}
                    </BulkWrapper>
                </Col>
            </Row>
            <Row justify='center' align='middle' className='cvat-resource-pagination-wrapper'>
                <Pagination
                    className='cvat-tasks-pagination'
                    onChange={(newPage: number, newPageSize: number) => {
                        dispatch(requestsActions.getRequests({
                            ...query,
                            page: newPage,
                            pageSize: newPageSize,
                        }, false));
                    }}
                    total={count}
                    current={page}
                    pageSize={pageSize}
                    showQuickJumper
                    showSizeChanger
                />
            </Row>
        </>
    );
}

export default React.memo(RequestsList);
