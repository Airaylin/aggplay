package com.river.aggplay

import android.service.quicksettings.TileService

/** 下拉通知栏「投递剪贴板」磁贴：点击拉起透明页读剪贴板并投递。 */
class QuickTile : TileService() {
    override fun onClick() {
        super.onClick()
        startActivityAndCollapse(
            android.content.Intent(this, ClipboardGrabActivity::class.java)
                .addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}
