#ifndef FINETERMINAL_SETTINGS_H
#define FINETERMINAL_SETTINGS_H

#include <QString>
#include <QStringList>
#include <QByteArray>
#include <QFont>

struct QuickCommand {
    QString name;
    QString command;
};

// 应用设置：基于 QSettings 持久化到 ~/.config/FineTerminal/FineTerminal.ini
class Settings {
public:
    static Settings &instance();

    void load();
    void save();

    // 外观
    QString colorScheme() const { return m_colorScheme; }
    void setColorScheme(const QString &v) { m_colorScheme = v; }
    QString fontFamily() const { return m_fontFamily; }
    void setFontFamily(const QString &v) { m_fontFamily = v; }
    int fontSize() const { return m_fontSize; }
    void setFontSize(int v) { m_fontSize = v; }
    qreal opacity() const { return m_opacity; }
    void setOpacity(qreal v) { m_opacity = v; }
    int historySize() const { return m_historySize; }
    void setHistorySize(int v) { m_historySize = v; }
    bool blinkingCursor() const { return m_blinkingCursor; }
    void setBlinkingCursor(bool v) { m_blinkingCursor = v; }

    // 行为
    QString shell() const { return m_shell; }
    void setShell(const QString &v) { m_shell = v; }
    bool confirmMultilinePaste() const { return m_confirmMultilinePaste; }
    void setConfirmMultilinePaste(bool v) { m_confirmMultilinePaste = v; }
    bool trimPaste() const { return m_trimPaste; }
    void setTrimPaste(bool v) { m_trimPaste = v; }

    // 安全认证
    bool hasPassword() const { return !m_passwordHash.isEmpty(); }
    // 设置新密码（明文 -> 加盐哈希存储）
    void setPassword(const QString &plain);
    bool verifyPassword(const QString &plain) const;
    bool lockOnStart() const { return m_lockOnStart; }
    void setLockOnStart(bool v) { m_lockOnStart = v; }
    bool lockOnIdle() const { return m_lockOnIdle; }
    void setLockOnIdle(bool v) { m_lockOnIdle = v; }
    int idleTimeoutMin() const { return m_idleTimeoutMin; }
    void setIdleTimeoutMin(int v) { m_idleTimeoutMin = v; }

    // 快捷命令
    QList<QuickCommand> quickCommands() const { return m_quickCommands; }
    void setQuickCommands(const QList<QuickCommand> &v);

    QFont terminalFont() const;

private:
    Settings() = default;

    QString m_colorScheme = QStringLiteral("DarkPastels");
    QString m_fontFamily = QStringLiteral("Monospace");
    int m_fontSize = 12;
    qreal m_opacity = 1.0;
    int m_historySize = 5000;
    bool m_blinkingCursor = true;

    QString m_shell; // 空则用 $SHELL
    bool m_confirmMultilinePaste = true;
    bool m_trimPaste = true;

    QByteArray m_passwordHash;
    QByteArray m_passwordSalt;
    bool m_lockOnStart = false;
    bool m_lockOnIdle = false;
    int m_idleTimeoutMin = 15;

    QList<QuickCommand> m_quickCommands;
};

#endif
