const reasons: Record<string, string> = {
  'Execution backend offline': '执行端离线，请等待电脑重新连接',
  'Backend has not advertised atomic request-owned images and busy rejection; update/reconnect the native backend':
    '电脑端尚未支持安全的消息与图片提交，请更新并重新连接执行端',
  'Backend image validation or upload limits are unavailable': '电脑端图片验证或上传限制不可用',
  'Session Hub does not expose this original App operation': '此来源尚未提供原应用中的这项操作',
  'Network file paths are not authorized': '网络文件路径未获授权',
  'Local image is outside allowed roots, missing, or too large': '本地图片不在授权目录内、已丢失或过大'
}
export const localizedReason = (reason?: string) => (reason ? reasons[reason] || reason : '')
