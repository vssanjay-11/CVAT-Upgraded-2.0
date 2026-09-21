// Copyright (C) 2020-2022 Intel Corporation
//
// SPDX-License-Identifier: MIT

import React from 'react';

import { Row, Col } from 'antd/lib/grid';
import Checkbox, { CheckboxChangeEvent } from 'antd/lib/checkbox';
import InputNumber from 'antd/lib/input-number';
import Text from 'antd/lib/typography/Text';
import Slider from 'antd/lib/slider';
import Select from 'antd/lib/select';
import Divider from 'antd/lib/divider';

import {
    MAX_ACCURACY,
} from 'components/annotation-page/standard-workspace/controls-side-bar/approximation-accuracy';
import { clamp } from 'utils/math';
import { DenseSegmentSettingsState } from 'reducers';

interface Props {
    autoSave: boolean;
    autoSaveInterval: number;
    focusedObjectPadding: number;
    showAllInterpolationTracks: boolean;
    showObjectsTextAlways: boolean;
    adaptiveZoom: boolean;
    intelligentPolygonCrop: boolean;
    defaultApproxPolyAccuracy: number;
    textFontSize: number;
    controlPointsSize: number;
    textPosition: 'center' | 'auto';
    textContent: string;
    showTagsOnFrame: boolean;
    denseSegment: DenseSegmentSettingsState;
    onSwitchAutoSave(enabled: boolean): void;
    onChangeAutoSaveInterval(interval: number): void;
    onChangeFocusedObjectPadding(padding: number): void;
    onChangeDefaultApproxPolyAccuracy(approxPolyAccuracy: number): void;
    onSwitchShowingInterpolatedTracks(enabled: boolean): void;
    onSwitchShowingObjectsTextAlways(enabled: boolean): void;
    onSwitchAdaptiveZoom(enabled: boolean): void;
    onSwitchIntelligentPolygonCrop(enabled: boolean): void;
    onChangeTextFontSize(fontSize: number): void;
    onChangeControlPointsSize(pointsSize: number): void;
    onChangeTextPosition(position: 'auto' | 'center'): void;
    onChangeTextContent(textContent: string[]): void;
    onSwitchShowingTagsOnFrame(enabled: boolean): void;
    onUpdateDenseSegmentSettings(settings: Partial<DenseSegmentSettingsState>): void;
}

function WorkspaceSettingsComponent(props: Props): JSX.Element {
    const {
        autoSave,
        autoSaveInterval,
        focusedObjectPadding,
        showAllInterpolationTracks,
        showObjectsTextAlways,
        adaptiveZoom,
        intelligentPolygonCrop,
        defaultApproxPolyAccuracy,
        textFontSize,
        controlPointsSize,
        textPosition,
        textContent,
        showTagsOnFrame,
        denseSegment,
        onSwitchAutoSave,
        onChangeAutoSaveInterval,
        onChangeFocusedObjectPadding,
        onSwitchShowingInterpolatedTracks,
        onSwitchShowingObjectsTextAlways,
        onSwitchAdaptiveZoom,
        onSwitchIntelligentPolygonCrop,
        onChangeDefaultApproxPolyAccuracy,
        onChangeTextFontSize,
        onChangeControlPointsSize,
        onChangeTextPosition,
        onChangeTextContent,
        onSwitchShowingTagsOnFrame,
        onUpdateDenseSegmentSettings,
    } = props;

    const minAutoSaveInterval = 1;
    const maxAutoSaveInterval = 60;
    const minFocusedObjectPadding = 0;
    const maxFocusedObjectPadding = 1000;
    const minControlPointsSize = 2;
    const maxControlPointsSize = 10;

    return (
        <div className='cvat-workspace-settings'>
            <Row className='cvat-player-setting'>
                <Col span={24}>
                    <Checkbox
                        className='cvat-text-color cvat-workspace-settings-auto-save'
                        checked={autoSave}
                        onChange={(event: CheckboxChangeEvent): void => {
                            onSwitchAutoSave(event.target.checked);
                        }}
                    >
                        Enable auto save
                    </Checkbox>
                </Col>
                <Col className='cvat-workspace-settings-auto-save-interval'>
                    <Text type='secondary'> Auto save every </Text>
                    <InputNumber
                        size='small'
                        min={minAutoSaveInterval}
                        max={maxAutoSaveInterval}
                        step={1}
                        value={Math.round(autoSaveInterval / (60 * 1000))}
                        onChange={(value: number | undefined | string): void => {
                            if (typeof value !== 'undefined') {
                                onChangeAutoSaveInterval(
                                    Math.floor(clamp(+value, minAutoSaveInterval, maxAutoSaveInterval)) * 60 * 1000,
                                );
                            }
                        }}
                    />
                    <Text type='secondary'> minutes </Text>
                </Col>
            </Row>
            <Row className='cvat-player-setting'>
                <Col span={12} className='cvat-workspace-settings-show-interpolated'>
                    <Row>
                        <Checkbox
                            className='cvat-text-color'
                            checked={showAllInterpolationTracks}
                            onChange={(event: CheckboxChangeEvent): void => {
                                onSwitchShowingInterpolatedTracks(event.target.checked);
                            }}
                        >
                            Show all interpolation tracks
                        </Checkbox>
                    </Row>
                    <Row>
                        <Text type='secondary'> Show hidden interpolated objects in the side panel</Text>
                    </Row>
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-show-text-always cvat-player-setting'>
                <Col span={24}>
                    <Checkbox
                        className='cvat-text-color'
                        checked={showObjectsTextAlways}
                        onChange={(event: CheckboxChangeEvent): void => {
                            onSwitchShowingObjectsTextAlways(event.target.checked);
                        }}
                    >
                        Always show object details
                    </Checkbox>
                </Col>
                <Col span={24}>
                    <Text type='secondary'>
                        Show text for an object on the canvas not only when the object is activated
                    </Text>
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-text-settings cvat-player-setting'>
                <Col span={24}>
                    <Text>Content of a text</Text>
                </Col>
                <Col span={16}>
                    <Select
                        className='cvat-workspace-settings-text-content'
                        mode='multiple'
                        value={textContent.split(',').filter((entry: string) => !!entry)}
                        onChange={onChangeTextContent}
                    >
                        <Select.Option value='id'>ID</Select.Option>
                        <Select.Option value='label'>Label</Select.Option>
                        <Select.Option value='attributes'>Attributes</Select.Option>
                        <Select.Option value='source'>Source</Select.Option>
                        <Select.Option value='descriptions'>Descriptions</Select.Option>
                        <Select.Option value='dimensions'>Dimensions</Select.Option>
                        <Select.Option value='layer'>Layer</Select.Option>
                    </Select>
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-text-settings cvat-player-setting'>
                <Col span={12}>
                    <Text>Position of a text</Text>
                </Col>
                <Col span={12}>
                    <Text>Font size of a text</Text>
                </Col>
                <Col span={12}>
                    <Select
                        className='cvat-workspace-settings-text-position'
                        value={textPosition}
                        onChange={onChangeTextPosition}
                    >
                        <Select.Option value='auto'>Auto</Select.Option>
                        <Select.Option value='center'>Center</Select.Option>
                    </Select>
                </Col>
                <Col span={12}>
                    <InputNumber
                        className='cvat-workspace-settings-text-size'
                        onChange={onChangeTextFontSize}
                        min={8}
                        max={20}
                        value={textFontSize}
                    />
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-adaptive-zoom cvat-player-setting'>
                <Col span={24}>
                    <Checkbox
                        className='cvat-text-color'
                        checked={adaptiveZoom}
                        onChange={(event: CheckboxChangeEvent): void => {
                            onSwitchAdaptiveZoom(event.target.checked);
                        }}
                    >
                        Adaptive zoom algorithm
                    </Checkbox>
                </Col>
                <Col span={24}>
                    <Text type='secondary'>
                        Enable smoother version of zooming, compatible with a trackpad and pinch gestures
                    </Text>
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-intelligent-polygon-cropping cvat-player-setting'>
                <Col span={24}>
                    <Checkbox
                        className='cvat-text-color'
                        checked={intelligentPolygonCrop}
                        onChange={(event: CheckboxChangeEvent): void => {
                            onSwitchIntelligentPolygonCrop(event.target.checked);
                        }}
                    >
                        Intelligent polygon cropping
                    </Checkbox>
                </Col>
                <Col span={24}>
                    <Text type='secondary'>Try to crop polygons automatically when editing</Text>
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-show-frame-tags cvat-player-setting'>
                <Col span={24}>
                    <Checkbox
                        className='cvat-text-color'
                        checked={showTagsOnFrame}
                        onChange={(event: CheckboxChangeEvent): void => {
                            onSwitchShowingTagsOnFrame(event.target.checked);
                        }}
                    >
                        Show tags on frame
                    </Checkbox>
                </Col>
                <Col span={24}>
                    <Text type='secondary'>Show frame tags in the corner of the workspace</Text>
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-focused-object-padding cvat-player-setting'>
                <Col>
                    <Text className='cvat-text-color'> Focused object padding </Text>
                    <InputNumber
                        min={minFocusedObjectPadding}
                        max={maxFocusedObjectPadding}
                        value={focusedObjectPadding}
                        onChange={(value: number | null): void => {
                            if (typeof value === 'number') {
                                onChangeFocusedObjectPadding(
                                    Math.floor(clamp(+value, minFocusedObjectPadding, maxFocusedObjectPadding)),
                                );
                            }
                        }}
                    />
                </Col>
                <Col span={24}>
                    <Text type='secondary'>Adds extra space in pixels around an object when it gets fitted</Text>
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-control-points-size cvat-player-setting'>
                <Col>
                    <Text className='cvat-text-color'> Control points size </Text>
                    <InputNumber
                        min={minControlPointsSize}
                        max={maxControlPointsSize}
                        value={controlPointsSize}
                        onChange={(value: number | undefined | string): void => {
                            if (typeof value !== 'undefined') {
                                onChangeControlPointsSize(
                                    Math.floor(clamp(+value, minControlPointsSize, maxControlPointsSize)),
                                );
                            }
                        }}
                    />
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-approx-poly-threshold cvat-player-setting'>
                <Col>
                    <Text className='cvat-text-color'>Default polygon simplification threshold</Text>
                </Col>
                <Col span={7} offset={1}>
                    <Slider
                        min={0}
                        max={MAX_ACCURACY}
                        step={1}
                        value={defaultApproxPolyAccuracy}
                        dots
                        onChange={onChangeDefaultApproxPolyAccuracy}
                    />
                </Col>
                <Col>
                    <Text type='secondary'>
                        Higher values preserve more polygon detail. Used for serverless interactors,
                        OpenCV scissors, and polygon simplification
                    </Text>
                </Col>
            </Row>
            <Divider orientation='left'>Dense Segmentation Defaults</Divider>
            <Row className='cvat-workspace-settings-dense-spacing cvat-player-setting'>
                <Col>
                    <Text className='cvat-text-color'>Max vertex spacing </Text>
                    <InputNumber
                        min={0.5}
                        max={50}
                        step={0.5}
                        value={denseSegment.maxVertexSpacing}
                        onChange={(val: number | null | undefined): void => {
                            if (typeof val === 'number') {
                                onUpdateDenseSegmentSettings({ maxVertexSpacing: val });
                            }
                        }}
                    />
                    <Text type='secondary'> px</Text>
                </Col>
                <Col span={24}>
                    <Text type='secondary'>
                        Target maximum distance between consecutive polygon vertices in pixels for dense boundaries
                    </Text>
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-dense-min-vertices cvat-player-setting'>
                <Col>
                    <Text className='cvat-text-color'>Minimum vertices </Text>
                    <InputNumber
                        min={10}
                        max={2000}
                        step={10}
                        value={denseSegment.minVertices}
                        onChange={(val: number | null | undefined): void => {
                            if (typeof val === 'number') {
                                onUpdateDenseSegmentSettings({ minVertices: Math.round(val) });
                            }
                        }}
                    />
                </Col>
                <Col span={24}>
                    <Text type='secondary'>
                        Ensures fine-grained boundary sampling even for small or tight contours
                    </Text>
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-dense-max-vertices cvat-player-setting'>
                <Col>
                    <Text className='cvat-text-color'>Maximum vertices </Text>
                    <InputNumber
                        min={100}
                        max={20000}
                        step={100}
                        value={denseSegment.maxVertices}
                        onChange={(val: number | null | undefined): void => {
                            if (typeof val === 'number') {
                                onUpdateDenseSegmentSettings({ maxVertices: Math.round(val) });
                            }
                        }}
                    />
                </Col>
                <Col span={24}>
                    <Text type='secondary'>
                        Upper bound on polygon vertices to maintain smooth rendering and interaction performance
                    </Text>
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-dense-area-mismatch cvat-player-setting'>
                <Col>
                    <Text className='cvat-text-color'>Max area mismatch tolerance </Text>
                    <InputNumber
                        min={0.1}
                        max={50}
                        step={0.5}
                        value={Math.round(denseSegment.maxAreaMismatch * 1000) / 10}
                        onChange={(val: number | null | undefined): void => {
                            if (typeof val === 'number') {
                                onUpdateDenseSegmentSettings({ maxAreaMismatch: val / 100 });
                            }
                        }}
                    />
                    <Text type='secondary'> %</Text>
                </Col>
                <Col span={24}>
                    <Text type='secondary'>
                        Flag polygon as needing review if polygon area deviates from mask area beyond this threshold
                    </Text>
                </Col>
            </Row>
            <Row className='cvat-workspace-settings-dense-batch-behavior cvat-player-setting'>
                <Col span={12}>
                    <Text className='cvat-text-color'>Default batch segmentation behavior</Text>
                </Col>
                <Col span={12}>
                    <Select
                        value={denseSegment.batchBehavior}
                        onChange={(val: 'append' | 'replace_matching' | 'replace_all'): void => {
                            onUpdateDenseSegmentSettings({ batchBehavior: val });
                        }}
                    >
                        <Select.Option value='append'>Append to existing</Select.Option>
                        <Select.Option value='replace_matching'>Replace matching labels</Select.Option>
                        <Select.Option value='replace_all'>Replace all annotations</Select.Option>
                    </Select>
                </Col>
                <Col span={24}>
                    <Text type='secondary'>
                        How multi-frame Segment Whole handles existing annotations on processed frames
                    </Text>
                </Col>
            </Row>
        </div>
    );
}

export default React.memo(WorkspaceSettingsComponent);
