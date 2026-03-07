-- 创建微信配置表
CREATE TABLE IF NOT EXISTS wechat_configs (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(100) NOT NULL COMMENT '配置名称',
    appid VARCHAR(100) NOT NULL COMMENT '微信AppID',
    token VARCHAR(100) NOT NULL COMMENT 'Token令牌',
    encoding_aes_key VARCHAR(255) NOT NULL COMMENT '消息加解密密钥',
    server_url VARCHAR(500) NULL COMMENT '服务器地址URL，格式：/wx_mp_cb?config_id=X',
    knowledge_base_id VARCHAR(100) NULL COMMENT '关联的知识库ID',
    welcome_message TEXT NULL COMMENT '关注时的欢迎消息',
    default_reply TEXT NULL COMMENT '默认回复消息',
    enable_ai_reply BOOLEAN DEFAULT TRUE COMMENT '是否启用公众号/服务号接入',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    INDEX idx_user_id (user_id),
    INDEX idx_appid (appid),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='微信公众号/服务号配置表';

-- 说明：
-- server_url 格式为 /wx_mp_cb?config_id=X
-- 前端会自动拼接当前域名，例如：https://chat.aigcqun.cn/wx_mp_cb?config_id=1
