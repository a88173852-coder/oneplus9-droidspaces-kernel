
/*
 * KernelSU / SukiSU support for non-GKI kernels.
 *
 * Kernel 5.9+ exposes path_mount() and KernelSU's own patch adds
 * path_umount().  On 5.4 both live under names that are file-local
 * (do_mount / do_umount), so export thin wrappers for the driver.
 *
 * 用途：<5.10 内核上 App Profile 的「Umount modules」与 SUSFS 的 sus_mount
 * 都要靠它按 App 卸载挂载点，官方文档也明确要求回移这个函数。
 */
int path_umount(struct path *path, int flags)
{
	struct mount *mnt = real_mount(path->mnt);
	int retval;

	if (path->dentry != path->mnt->mnt_root)
		return -EINVAL;

	down_write(&namespace_sem);
	retval = do_umount(mnt, flags);
	up_write(&namespace_sem);
	return retval;
}
EXPORT_SYMBOL(path_umount);
