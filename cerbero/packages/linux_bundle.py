# cerbero - a multi-platform build system for Open Source software
# Copyright (C) 2014 Thibault Saunier <tsaunier@gnome.org>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Library General Public
# License as published by the Free Software Foundation; either
# version 2 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Library General Public License for more details.
#
# You should have received a copy of the GNU Library General Public
# License along with this library; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place - Suite 330,
# Boston, MA 02111-1307, USA.


import os

from cerbero.errors import FatalError
from cerbero.utils import _, N_, shell
from cerbero.utils import messages as m
from cerbero.packages import PackagerBase
from cerbero.config import DistroVersion

APPRUN_TPL = """#!/bin/sh

# Base environment variables
export LD_LIBRARY_PATH=${APPDIR}/lib:${LD_LIBRARY_PATH}
export PATH=${APPDIR}/bin:${PATH}
export XDG_DATA_DIRS=${APPDIR}/share:${XDG_DATA_DIRS}
# GTK+/GIO/GdkPixbuf environment variables
# http://askubuntu.com/questions/251712/how-can-i-install-a-gsettings-schema-without-root-privileges
export GSETTINGS_SCHEMA_DIR=${APPDIR}/share/glib-2.0/schemas/:${GSETTINGS_SCHEMA_DIR}
export GDK_PIXBUF_MODULE_FILE=${APPDIR}/lib/gdk-pixbuf-2.0/2.10.0/loaders.cache
export GTK_PATH=${APPDIR}/lib/gtk-3.0
export GTK_DATA_PREFIX=${APPDIR}
export GTK_THEME=Adwaita
# GStreamer environment variables
export GST_REGISTRY=HOME}/.cache/gstreamer-1.0/%(appname)s-bundle-registry
export GST_PLUGIN_SCANNER=${APPDIR}/libexec/gstreamer-1.0/gst-plugin-scanner
export GST_PLUGIN_SYSTEM_PATH=

# Try to discover plugins only once
PLUGINS_SYMLINK=${HOME}/.cache/gstreamer-1.0/%(appname)s-gstplugins
ln -s ${APPDIR}/lib/gstreamer-1.0/ ${PLUGINS_SYMLINK}
if [ $? -ne 0 ]; then
    export GST_PLUGIN_PATH=${APPDIR}/lib/gstreamer-1.0/
else
    export GST_PLUGIN_PATH=${PLUGINS_SYMLINK}
fi

export GST_REGISTRY=${HOME}/.cache/gstreamer-1.0/%(appname)s-bundle-registry
# Python
export PYTHONPATH=${APPDIR}/%(py_prefix)s/site-packages${PYTHONPATH:+:$PYTHONPATH}
export GI_TYPELIB_PATH=${APPDIR}/lib/girepository-1.0

# Currently we change into the APPDIR directory, this only because of gdk-pixbuf
# and pango cache files which need to specify relative paths.
cd ${APPDIR}

export PYTHONHOME=${APPDIR}
if test -z ${APP_IMAGE_TEST}; then
    # Invoke the app with the arguments passed
    ${APPDIR}/%(executable_path)s $*
else
    # Run a shell in test mode
    bash;
fi

# Cleaning up the link to gstplugins
rm ${PLUGINS_SYMLINK}
"""

class Bundler(PackagerBase):
    doc = N_('Bundle after building packages')
    name = 'bundle'

    def __init__(self, config, package, store):
        PackagerBase.__init__(self, config, package, store)
        self.bundle_name = "%s-%s-%s" %(self.package.name, self.package.version, self.config.arch)

    def pack(self, output_dir, devel=True, force=False, keep_temp=False):
        self.tmp_install_dir = os.path.join(output_dir, "bundle_root")
        self.desktop_file = os.path.join(self.tmp_install_dir, self.package.desktop_file)
        self.output_dir = output_dir
        self.devel = devel
        self.keep_temp = keep_temp

        self.bundle()

        return []

    def _copy_installdir(self):
        shell.call("rm -rf %s" %(self.tmp_install_dir), fail=False)
        shell.call("cp -pR %s %s" %(self.config.install_dir, self.tmp_install_dir))

    def _clean_install_path(self):
        for command in ["rm -f `find -name '*.a'`",
                        "rm -f `find -name '*.la'`",
                        "rm -rf include"]:
            shell.call(command, self.tmp_install_dir, fail=False)

        # FIXME Find a clean way to handle that
        shell.call("rm -f $(ls | grep -v 'gst*\|pitivi\|ges*\|gtk-update-icon-cache\|python*')",
                    os.path.join(self.tmp_install_dir, "bin"), fail=False)

        for rdir in [ "man", "info", "help", "doc", "gtk-doc", "gdb", "gdm", "vala",
                "pkgconfig", "gnome", "xml", "bash-completion", "appdata", "dbus-1",
                    "glib-2.0/codegen", "glib-2.0/gdb", "glib-2.0/gettext"]:
            try:
                os.rmdir(os.path.join(self.tmp_install_dir, "share", rdir))
                m.message("Removed: %s" % os.path.join(self.tmp_install_dir, "share", rdir))
            except OSError:
                pass

    def _make_paths_relative(self):
        sofiles = shell.find_files('*.so', self.tmp_install_dir)
        for sof in sofiles:
            try:
                shell.call("chrpath -d %s" % sof, self.tmp_install_dir,
                           fail=False)
            except FatalError:
                m.warning("Could not 'chrpath' %s" % sof)

        shell.call("ln -s . usr", self.tmp_install_dir, fail=False)

        # FIXME Fix the root of that issue !
        # Make libbz2.so symlinks relative
        for command in ["rm libbz2.so libbz2.so.1.0",
                        "ln -s libbz2.so.1.0.6 libbz2.so",
                        "ln -s libbz2.so.1.0.6 libbz2.so.1.0",
                        ]:
            shell.call(command, os.path.join(self.tmp_install_dir, "lib"), False)

        # Post process the loaders.cache file to use relative paths, we use a for loop here
        # just because we're not sure the exact location, it could be in lib or lib64
        shell.call("for cache in `find %s -path '*gdk-pixbuf-*/*/loaders.cache'`; do "
                   "cat $cache | sed -e 's|%s|\./|g' > $cache.1 && mv $cache.1 $cache;"
                   "done" % (self.tmp_install_dir, self.config.install_dir))

        for icondir in os.listdir(os.path.join(self.tmp_install_dir, "share/icons/")):
            if os.path.exists(os.path.join(icondir, "index.theme")):
                shell.call("gtk-update-icon-cache %s" % icondir, fail=False)

        shell.call("update-mime-database %s" % os.path.join(self.tmp_install_dir, "share", "mime"), fail=False)

        shell.call("rm -rf %s" % os.path.join(self.tmp_install_dir, "share", "applications"), fail=False)
        shell.call("ln -s %s %s" % (os.path.join("/usr", "share", "applications"),
                                    os.path.join(self.tmp_install_dir, "share", "applications")),
                   fail=False)

    def _install_bundle_specific_files(self):
        # Installing desktop file and runner script
        shell.call("cp %s %s" % (self.desktop_file, self.tmp_install_dir), fail=False)
        filepath = os.path.join(self.tmp_install_dir, "AppRun")
        f = open (filepath, 'w+')

        f.write(APPRUN_TPL % {"prefix": self.tmp_install_dir,
                              "executable_path": self.package.executable_path,
                              "appname": self.package.name,
                              "py_prefix": self.config.py_prefix})
        f.close()
        shell.call("chmod +x %s" % filepath)

    def _generate_bundle(self):
        shell.call("rm -rf %s" % (os.path.join(self.output_dir, self.bundle_name)), fail=False)
        shell.call("AppImageAssistant %s %s" % (self.tmp_install_dir, self.bundle_name),
                   self.output_dir)

    def _clean_tmps(self):
        shell.call("rm -rf %s", self.tmp_install_dir)

    def _create_tarball(self):
        md5name = "%s.md5sum" % self.bundle_name
        shell.call("md5sum %s > %s" % (self.bundle_name, md5name),
                   self.output_dir)
        m.action(_("Bundle avalaible in: %s") % os.path.join(self.output_dir, self.bundle_name))

    def bundle(self):
        # If not devel wanted, we make a clean bundle with only
        # file needed to execute
        steps = [
            ("prepare-install-dir",
             [(_("Copy install path"), self._copy_installdir, True),
              (_("Cleaning install path"), self._clean_install_path, not self.devel),
              (_("Installing bundle files"), self._install_bundle_specific_files, True),
              (_("Make all paths relatives"), self._make_paths_relative, True),
              ]
            ),
            ("generate-tarball",
             [(_("Running AppImageAssistant"), self._generate_bundle, True),
              (_("Generating md5"), self._create_tarball, True)
             ]
            ),
            ("clean-install-dir",
             [(_("Clean tmp dirs"), self._clean_tmps, not self.keep_temp)]
            )
        ]

        for step in steps:
            shell.set_logfile_output("%s/%s-bundle-%s.log" % (self.config.logs, self.package.name, step[0]))
            for substep in step[1]:
                m.build_step('1', '1', self.package.name + " linux bundle", substep[0])
                if substep[2] is True:
                    substep[1]()
                else:
                    m.action(_("Step not wanted"))
            shell.close_logfile_output()
