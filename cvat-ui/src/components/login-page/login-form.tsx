// Copyright (C) 2020-2022 Intel Corporation
// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useState } from 'react';
import { Link } from 'react-router-dom';

import Form from 'antd/lib/form';
import Button from 'antd/lib/button';
import Input from 'antd/lib/input';
import Alert from 'antd/lib/alert';
import { Col, Row } from 'antd/lib/grid';
import Title from 'antd/lib/typography/Title';
import Text from 'antd/lib/typography/Text';
import Icon from '@ant-design/icons';
import {
    BackArrowIcon, ClearIcon,
} from 'icons';

const OAUTH_ERROR_MESSAGES: Record<string, string> = {
    OAUTH_CONFIGURATION_ERROR: 'Google OAuth is not configured on the server. Please verify GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.',
    OAUTH_REDIRECT_MISMATCH: 'Google OAuth redirect URI mismatch. Please verify Google Cloud Console credentials.',
    OAUTH_STATE_INVALID: 'Invalid OAuth security state. Please retry signing in.',
    OAUTH_TOKEN_EXCHANGE_FAILED: 'Could not exchange authorization code with Google. Please retry.',
    OAUTH_ID_TOKEN_INVALID: 'Google ID token validation failed. Please check credentials.',
    OAUTH_EMAIL_NOT_VERIFIED: 'Your Google email address has not been verified by Google.',
    OAUTH_SESSION_CREATION_FAILED: 'Failed to establish persistent session on server.',
    google_auth_failed: 'Google sign-in could not be completed. Please try again or sign in with password.',
};

import CVATSigningInput, { CVATInputType } from 'components/signing-common/cvat-signing-input';
import { CombinedState } from 'reducers';
import { useAuthQuery, usePlugins } from 'utils/hooks';

export interface LoginData {
    credential: string;
    password: string;
}

interface Props {
    renderResetPassword: boolean;
    renderRegistrationComponent: boolean;
    renderBasicLoginComponent: boolean;
    fetching: boolean;
    onSubmit(loginData: LoginData): void;
}

function LoginFormComponent(props: Props): JSX.Element {
    const {
        fetching, onSubmit, renderResetPassword, renderRegistrationComponent, renderBasicLoginComponent,
    } = props;

    const authQuery = useAuthQuery();
    const [form] = Form.useForm();
    const [credential, setCredential] = useState('');
    const pluginsToRender = usePlugins(
        (state: CombinedState) => state.plugins.components.loginPage.loginForm,
        props,
        { credential },
    );

    let resetSearch = authQuery ? new URLSearchParams(authQuery).toString() : '';
    if (credential.includes('@')) {
        const updatedAuthQuery = authQuery ? { ...authQuery, email: credential } : { email: credential };
        resetSearch = new URLSearchParams(updatedAuthQuery).toString();
    }

    const forgotPasswordLink = (
        <Col className='cvat-credentials-link'>
            <Text strong>
                <Link to={{ pathname: '/auth/password/reset', search: resetSearch }}>
                    Forgot password?
                </Link>
            </Text>
        </Col>
    );

    return (
        <div className='cvat-login-form-wrapper'>
            <Row justify='space-between' className='cvat-credentials-navigation'>
                {
                    credential && (
                        <Col>
                            <Icon
                                component={BackArrowIcon}
                                onClick={() => {
                                    setCredential('');
                                    form.setFieldsValue({ credential: '' });
                                }}
                            />
                        </Col>
                    )
                }
                {
                    !credential && renderRegistrationComponent && (
                        <Row>
                            <Col className='cvat-credentials-link'>
                                <Text strong>
                                    New user?&nbsp;
                                    <Link to={{
                                        pathname: '/auth/register',
                                        search: authQuery ? new URLSearchParams(authQuery).toString() : '',
                                    }}
                                    >
                                        Create an account
                                    </Link>
                                </Text>
                            </Col>
                        </Row>
                    )
                }
                {
                    renderResetPassword && forgotPasswordLink
                }
            </Row>
            {(() => {
                const urlParams = new URLSearchParams(window.location.search);
                const errCode = urlParams.get('error');
                if (!errCode) return null;
                const message = OAUTH_ERROR_MESSAGES[errCode] || `Sign in error: ${errCode}`;
                return (
                    <Alert
                        message='Authentication Notice'
                        description={message}
                        type='error'
                        showIcon
                        closable
                        style={{ marginBottom: '16px' }}
                    />
                );
            })()}
            <Col>
                <Title level={2}> Sign in </Title>
            </Col>
            <Button
                type='default'
                size='large'
                className='cvat-google-login-button'
                style={{
                    width: '100%',
                    height: '44px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: '12px',
                    borderRadius: '8px',
                    border: '1px solid #dadce0',
                    fontWeight: 500,
                    marginBottom: '16px',
                    backgroundColor: '#ffffff',
                    color: '#3c4043',
                    boxShadow: '0 1px 2px rgba(60,64,67,0.08)',
                }}
                onClick={async () => {
                    try {
                        const resp = await fetch('/api/auth/google/url');
                        if (resp.ok) {
                            const data = await resp.json();
                            if (data.url) {
                                window.location.href = data.url;
                                return;
                            }
                        }
                    } catch (e) {
                        // fallback
                    }
                    window.location.href = '/api/auth/google/url';
                }}
            >
                <svg width='18' height='18' viewBox='0 0 24 24'>
                    <path fill='#4285F4' d='M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z' />
                    <path fill='#34A853' d='M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z' />
                    <path fill='#FBBC05' d='M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l2.85-2.22.81-.63z' />
                    <path fill='#EA4335' d='M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.84c.87-2.6 3.3-4.52 6.16-4.52z' />
                </svg>
                Continue with Google
            </Button>
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: '20px', color: '#8c8c8c' }}>
                <div style={{ flex: 1, height: '1px', backgroundColor: '#f0f0f0' }} />
                <span style={{ padding: '0 12px', fontSize: '13px' }}>or sign in with password</span>
                <div style={{ flex: 1, height: '1px', backgroundColor: '#f0f0f0' }} />
            </div>
            <Form
                className={`cvat-login-form ${credential ? 'cvat-login-form-extended' : ''}`}
                form={form}
                onFinish={(loginData: LoginData) => {
                    onSubmit(loginData);
                }}
            >
                {renderBasicLoginComponent && (
                    <>
                        <Form.Item
                            className='cvat-credentials-form-item'
                            name='credential'
                        >
                            <Input
                                autoComplete='credential'
                                prefix={<Text>Email or username</Text>}
                                className={credential ? 'cvat-input-floating-label-above' : 'cvat-input-floating-label'}
                                suffix={credential && (
                                    <Icon
                                        component={ClearIcon}
                                        onClick={() => {
                                            setCredential('');
                                            form.setFieldsValue({ credential: '', password: '' });
                                        }}
                                    />
                                )}
                                onChange={(event) => {
                                    const { value } = event.target;
                                    setCredential(value);
                                    if (!value) form.setFieldsValue({ credential: '', password: '' });
                                }}
                            />
                        </Form.Item>
                        {
                            credential && (
                                <Form.Item
                                    className='cvat-credentials-form-item'
                                    name='password'
                                    rules={[
                                        {
                                            required: true,
                                            message: 'Please specify a password',
                                        },
                                    ]}
                                >
                                    <CVATSigningInput
                                        type={CVATInputType.PASSWORD}
                                        id='password'
                                        placeholder='Password'
                                        autoComplete='password'
                                    />
                                </Form.Item>
                            )
                        }
                        {
                            !!credential && (
                                <Form.Item>
                                    <Button
                                        className='cvat-credentials-action-button'
                                        loading={fetching}
                                        disabled={!credential}
                                        htmlType='submit'
                                    >
                                        Next
                                    </Button>
                                </Form.Item>
                            )
                        }
                    </>
                )}
                {
                    pluginsToRender.map(({ component: Component }, index) => (
                        <Component targetProps={props} targetState={{ credential }} key={index} />
                    ))
                }
            </Form>
        </div>
    );
}

export default React.memo(LoginFormComponent);
