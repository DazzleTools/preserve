"""
Manifest management for preserve.py.

This module handles creation, updating, and reading of operation manifests,
which track file operations, metadata, and provide support for reversibility.
"""

import os
import sys
import json
import hashlib
import datetime
import platform
import logging
import socket
import uuid
from pathlib import Path
from typing import Dict, List, Any, Optional, Union, Set, Tuple

# Set up module-level logger
logger = logging.getLogger(__name__)

class PreserveManifest:
    """
    Manifest for tracking file operations and metadata.

    The manifest stores information about:
    - Source and destination paths for each file
    - File metadata (timestamps, permissions, etc.)
    - Hash values for verification
    - Operation history for reproducibility

    Schema v3.0 (0.7.x) adds DAG support:
    - manifest_id: Unique identifier for this manifest
    - parent_ids: Array of parent manifest IDs (enables DAG for lineage tracking)
    - lineage: Helper fields for fast ancestry queries
    """

    def __init__(self, manifest_path: Optional[Union[str, Path]] = None):
        """
        Initialize a new or existing manifest.

        Args:
            manifest_path: Path to an existing manifest file to load (optional)
        """
        # Default manifest structure (v3.0 schema)
        self.manifest = {
            "manifest_version": 3,
            "manifest_id": self._generate_manifest_id(),
            "parent_ids": [],  # DAG support: array of parent manifest IDs
            "lineage": {
                "root_id": None,  # ID of first ancestor with no parents
                "depth": 0,       # Distance from root
                "is_merge": False # True if multiple parents (0.8.x feature)
            },
            "created_at": datetime.datetime.now().isoformat(),
            "updated_at": datetime.datetime.now().isoformat(),
            "platform": self._get_platform_info(),
            "host_info": self._get_host_info(),
            "operations": [],
            "files": {},
            "metadata": {},
            "extensions": {}  # Reserved for dazzlelink, etc.
        }

        # Load existing manifest if provided
        if manifest_path:
            self.load(manifest_path)

    def _generate_manifest_id(self) -> str:
        """
        Generate a unique manifest ID.

        For v3.0, uses UUID. In future versions (0.8.x+), this could
        become content-addressable (sha256 of manifest content).

        Returns:
            Unique manifest ID string
        """
        return f"pm-{uuid.uuid4().hex[:12]}"
    
    def _get_platform_info(self) -> Dict[str, str]:
        """
        Get information about the current platform.

        Returns:
            Dictionary with platform information
        """
        return {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version()
        }

    def _get_host_info(self) -> Dict[str, Any]:
        """
        Get comprehensive information about the host machine.

        Returns:
            Dictionary with host information including hostname, FQDN, MAC address, etc.
        """
        host_info = {}

        try:
            # Basic hostname information
            host_info["hostname"] = socket.gethostname()
            host_info["fqdn"] = socket.getfqdn()

            # IP addresses
            try:
                host_info["ip_addresses"] = []
                # Get all IP addresses
                hostname = socket.gethostname()
                for info in socket.getaddrinfo(hostname, None):
                    ip = info[4][0]
                    if ip not in host_info["ip_addresses"]:
                        host_info["ip_addresses"].append(ip)
            except:
                host_info["ip_addresses"] = []

            # MAC address (as a stable machine identifier)
            try:
                mac_num = uuid.getnode()
                mac = ':'.join(('%012X' % mac_num)[i:i+2] for i in range(0, 12, 2))
                host_info["mac_address"] = mac
                host_info["mac_address_int"] = mac_num
            except:
                host_info["mac_address"] = None
                host_info["mac_address_int"] = None

            # Machine-specific ID
            host_info["machine_id"] = self._get_machine_id()

            # Check if running in container or VM
            host_info["is_container"] = self._detect_container()
            host_info["is_vm"] = self._detect_vm()

        except Exception as e:
            logger.warning(f"Error collecting host info: {e}")
            # Return minimal info on error
            host_info = {
                "hostname": "unknown",
                "error": str(e)
            }

        return host_info

    def _get_machine_id(self) -> Optional[str]:
        """
        Get a stable machine identifier that persists across reboots.

        Returns:
            Machine ID string or None if not available
        """
        try:
            if platform.system() == 'Windows':
                # On Windows, try to get the MachineGuid from registry
                try:
                    import winreg
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                       r"SOFTWARE\Microsoft\Cryptography") as key:
                        return winreg.QueryValueEx(key, "MachineGuid")[0]
                except:
                    pass
            elif platform.system() == 'Linux':
                # On Linux, try to read machine-id
                machine_id_paths = [
                    '/etc/machine-id',
                    '/var/lib/dbus/machine-id'
                ]
                for path in machine_id_paths:
                    try:
                        with open(path, 'r') as f:
                            return f.read().strip()
                    except:
                        continue
            elif platform.system() == 'Darwin':  # macOS
                # On macOS, use system profiler
                try:
                    import subprocess
                    result = subprocess.run(
                        ['system_profiler', 'SPHardwareDataType'],
                        capture_output=True, text=True
                    )
                    for line in result.stdout.split('\n'):
                        if 'Hardware UUID' in line:
                            return line.split(':')[1].strip()
                except:
                    pass
        except Exception as e:
            logger.debug(f"Could not get machine ID: {e}")

        # Fallback to MAC address as machine ID
        try:
            return str(uuid.getnode())
        except:
            return None

    def _detect_container(self) -> bool:
        """
        Detect if running inside a container.

        Returns:
            True if running in a container, False otherwise
        """
        try:
            # Check for Docker
            if os.path.exists('/.dockerenv'):
                return True

            # Check for Kubernetes
            if os.path.exists('/var/run/secrets/kubernetes.io'):
                return True

            # Check cgroup for docker/lxc/etc
            if os.path.exists('/proc/1/cgroup'):
                with open('/proc/1/cgroup', 'r') as f:
                    content = f.read()
                    if any(x in content for x in ['docker', 'lxc', 'containerd', 'kubepods']):
                        return True
        except:
            pass

        return False

    def _detect_vm(self) -> bool:
        """
        Detect if running inside a virtual machine.

        Returns:
            True if running in a VM, False otherwise
        """
        try:
            system = platform.system()

            if system == 'Linux':
                # Check for common VM indicators
                try:
                    import subprocess
                    result = subprocess.run(['systemd-detect-virt'],
                                          capture_output=True, text=True)
                    if result.returncode == 0 and result.stdout.strip() != 'none':
                        return True
                except:
                    pass

                # Check DMI info
                dmi_paths = ['/sys/class/dmi/id/product_name',
                           '/sys/class/dmi/id/sys_vendor']
                vm_indicators = ['VirtualBox', 'VMware', 'QEMU', 'Xen', 'Hyper-V',
                                'KVM', 'Parallels', 'Virtual Machine']

                for path in dmi_paths:
                    try:
                        with open(path, 'r') as f:
                            content = f.read().strip()
                            if any(ind in content for ind in vm_indicators):
                                return True
                    except:
                        pass

            elif system == 'Windows':
                # Check for VM-specific registry keys or WMI
                try:
                    import subprocess
                    result = subprocess.run(
                        ['wmic', 'computersystem', 'get', 'model'],
                        capture_output=True, text=True
                    )
                    if any(x in result.stdout for x in ['VirtualBox', 'VMware', 'Virtual']):
                        return True
                except:
                    pass
        except:
            pass

        return False
    
    def load(self, path: Union[str, Path]) -> bool:
        """
        Load a manifest from a file.

        Supports manifest versions 1, 2, and 3 with automatic migration
        of older formats to include v3 fields.

        Args:
            path: Path to the manifest file

        Returns:
            True if successful, False otherwise
        """
        try:
            path = Path(path)

            if not path.exists():
                logger.warning(f"Manifest file does not exist: {path}")
                return False

            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Validate manifest version (support v1, v2, and v3)
            manifest_version = data.get("manifest_version", 1)
            if manifest_version not in [1, 2, 3]:
                logger.warning(f"Unsupported manifest version: {manifest_version}")
                return False

            # Migrate v1 manifest to include host_info
            if manifest_version == 1:
                data["host_info"] = {
                    "hostname": "unknown (v1 manifest)",
                    "note": "Manifest created before host tracking was added"
                }

            # Migrate v1/v2 manifests to include v3 DAG fields
            if manifest_version < 3:
                # Add manifest_id if missing
                if "manifest_id" not in data:
                    data["manifest_id"] = self._generate_manifest_id()
                # Add parent_ids if missing (empty for migrated manifests)
                if "parent_ids" not in data:
                    data["parent_ids"] = []
                # Add lineage if missing
                if "lineage" not in data:
                    data["lineage"] = {
                        "root_id": data.get("manifest_id"),
                        "depth": 0,
                        "is_merge": False
                    }
                # Add extensions if missing
                if "extensions" not in data:
                    data["extensions"] = {}
                logger.debug(f"Migrated v{manifest_version} manifest to v3 format")

            # Update manifest with loaded data
            self.manifest = data
            logger.debug(f"Loaded manifest from {path}")
            return True

        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in manifest file: {path}")
            return False
        except Exception as e:
            logger.error(f"Error loading manifest: {e}")
            return False
    
    def save(self, path: Union[str, Path]) -> bool:
        """
        Save the manifest to a file.
        
        Args:
            path: Path to save the manifest
            
        Returns:
            True if successful, False otherwise
        """
        try:
            path = Path(path)
            
            # Create parent directory if it doesn't exist
            path.parent.mkdir(parents=True, exist_ok=True)
            
            # Update updated_at timestamp
            self.manifest["updated_at"] = datetime.datetime.now().isoformat()
            
            # Convert all Path objects to strings
            manifest_copy = self._prepare_manifest_for_serialization()
            
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(manifest_copy, f, indent=2)
            
            logger.debug(f"Saved manifest to {path}")
            return True
            
        except Exception as e:
            logger.error(f"Error saving manifest: {e}")
            return False
            
    def _prepare_manifest_for_serialization(self) -> Dict[str, Any]:
        """
        Create a serializable copy of the manifest.
        
        Returns:
            A JSON-serializable copy of the manifest
        """
        def convert_paths_to_strings(obj):
            if isinstance(obj, Path):
                return str(obj)
            elif isinstance(obj, dict):
                return {k: convert_paths_to_strings(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_paths_to_strings(item) for item in obj]
            else:
                return obj
                
        return convert_paths_to_strings(self.manifest)
    
    def add_operation(self, operation_type: str, source_path: Optional[str] = None, 
                     destination_path: Optional[str] = None, options: Optional[Dict[str, Any]] = None,
                     command_line: Optional[str] = None) -> int:
        """
        Add an operation to the manifest.
        
        Args:
            operation_type: Type of operation (COPY, MOVE, VERIFY, RESTORE)
            source_path: Source path for the operation (optional)
            destination_path: Destination path for the operation (optional)
            options: Additional operation options (optional)
            command_line: Original command line that triggered the operation (optional)
            
        Returns:
            The operation ID (index in the operations list)
        """
        operation = {
            "id": len(self.manifest["operations"]),
            "type": operation_type,
            "timestamp": datetime.datetime.now().isoformat(),
            "options": options or {}
        }
        
        if source_path:
            operation["source_path"] = source_path
        
        if destination_path:
            operation["destination_path"] = destination_path
        
        if command_line:
            operation["command_line"] = command_line
        
        self.manifest["operations"].append(operation)
        return operation["id"]
    
    def add_file(self, source_path: str, destination_path: str, 
                file_info: Optional[Dict[str, Any]] = None, operation_id: Optional[int] = None,
                file_id: Optional[str] = None) -> str:
        """
        Add a file entry to the manifest.
        
        Args:
            source_path: Original path of the file
            destination_path: Destination path of the file
            file_info: Additional file metadata (optional)
            operation_id: ID of the operation that processed this file (optional)
            file_id: Custom file ID (optional, defaults to destination path)
            
        Returns:
            The file ID used to reference this file in the manifest
        """
        # Use destination path as default file ID
        if not file_id:
            file_id = destination_path
        
        # Create or update file entry
        if file_id not in self.manifest["files"]:
            self.manifest["files"][file_id] = {
                "source_path": source_path,
                "destination_path": destination_path,
                "added_at": datetime.datetime.now().isoformat(),
                "history": []
            }
        else:
            # Update existing entry with new paths
            self.manifest["files"][file_id]["source_path"] = source_path
            self.manifest["files"][file_id]["destination_path"] = destination_path
            self.manifest["files"][file_id]["updated_at"] = datetime.datetime.now().isoformat()
        
        # Add file info if provided
        if file_info:
            for key, value in file_info.items():
                self.manifest["files"][file_id][key] = value
        
        # Add to operation history if operation ID provided
        if operation_id is not None:
            history_entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "operation_id": operation_id
            }
            self.manifest["files"][file_id]["history"].append(history_entry)
        
        return file_id
    
    def update_file_metadata(self, file_id: str, metadata: Dict[str, Any]) -> bool:
        """
        Update metadata for a file.
        
        Args:
            file_id: The file ID to update
            metadata: The metadata to update
            
        Returns:
            True if successful, False if file not found
        """
        if file_id not in self.manifest["files"]:
            logger.warning(f"File not found in manifest: {file_id}")
            return False
        
        # Update metadata
        for key, value in metadata.items():
            self.manifest["files"][file_id][key] = value
        
        # Add updated timestamp
        self.manifest["files"][file_id]["updated_at"] = datetime.datetime.now().isoformat()
        
        return True
    
    def add_file_hash(self, file_id: str, algorithm: str, hash_value: str) -> bool:
        """
        Add a hash value for a file.
        
        Args:
            file_id: The file ID
            algorithm: Hash algorithm (MD5, SHA1, SHA256, SHA512)
            hash_value: The computed hash value
            
        Returns:
            True if successful, False if file not found
        """
        if file_id not in self.manifest["files"]:
            logger.warning(f"File not found in manifest: {file_id}")
            return False
        
        # Ensure hashes dictionary exists
        if "hashes" not in self.manifest["files"][file_id]:
            self.manifest["files"][file_id]["hashes"] = {}
        
        # Add or update hash value
        self.manifest["files"][file_id]["hashes"][algorithm] = hash_value
        
        return True
    
    def get_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        """
        Get information about a file.
        
        Args:
            file_id: The file ID
            
        Returns:
            File information or None if not found
        """
        return self.manifest["files"].get(file_id)
    
    def get_file_by_destination(self, destination_path: str) -> Optional[Dict[str, Any]]:
        """
        Get a file by its destination path.
        
        Args:
            destination_path: The destination path to look for
            
        Returns:
            File information or None if not found
        """
        for file_id, file_info in self.manifest["files"].items():
            if file_info.get("destination_path") == destination_path:
                return file_info
        return None
    
    def get_file_by_source(self, source_path: str) -> Optional[Dict[str, Any]]:
        """
        Get a file by its source path.
        
        Args:
            source_path: The source path to look for
            
        Returns:
            File information or None if not found
        """
        for file_id, file_info in self.manifest["files"].items():
            if file_info.get("source_path") == source_path:
                return file_info
        return None
    
    def get_all_files(self) -> Dict[str, Dict[str, Any]]:
        """
        Get all files in the manifest.
        
        Returns:
            Dictionary of file_id -> file_info
        """
        return self.manifest["files"]
    
    def get_operation(self, operation_id: int) -> Optional[Dict[str, Any]]:
        """
        Get information about an operation.
        
        Args:
            operation_id: The operation ID
            
        Returns:
            Operation information or None if not found
        """
        if 0 <= operation_id < len(self.manifest["operations"]):
            return self.manifest["operations"][operation_id]
        return None
    
    def get_last_operation(self) -> Optional[Dict[str, Any]]:
        """
        Get the last operation in the manifest.
        
        Returns:
            Last operation or None if no operations
        """
        if self.manifest["operations"]:
            return self.manifest["operations"][-1]
        return None
    
    def get_all_operations(self) -> List[Dict[str, Any]]:
        """
        Get all operations in the manifest.
        
        Returns:
            List of operations
        """
        return self.manifest["operations"]
    
    def set_metadata(self, key: str, value: Any) -> None:
        """
        Set a metadata value in the manifest.
        
        Args:
            key: Metadata key
            value: Metadata value
        """
        self.manifest["metadata"][key] = value
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """
        Get a metadata value from the manifest.
        
        Args:
            key: Metadata key
            default: Default value if key not found
            
        Returns:
            Metadata value or default
        """
        return self.manifest["metadata"].get(key, default)
    
    def get_all_metadata(self) -> Dict[str, Any]:
        """
        Get all metadata from the manifest.
        
        Returns:
            Metadata dictionary
        """
        return self.manifest["metadata"]
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Get the manifest as a dictionary.
        
        Returns:
            The manifest dictionary
        """
        return self.manifest.copy()
    
    def get_files_for_operation(self, operation_id: int) -> Dict[str, Dict[str, Any]]:
        """
        Get all files processed by a specific operation.
        
        Args:
            operation_id: The operation ID
            
        Returns:
            Dictionary of file_id -> file_info for files in the operation
        """
        result = {}
        
        for file_id, file_info in self.manifest["files"].items():
            if "history" in file_info:
                for entry in file_info["history"]:
                    if entry.get("operation_id") == operation_id:
                        result[file_id] = file_info
                        break
        
        return result
    
    def get_files_by_state(self, state: str) -> Dict[str, Dict[str, Any]]:
        """
        Get files by their current state.
        
        Args:
            state: File state (e.g., "copied", "verified", "missing")
            
        Returns:
            Dictionary of file_id -> file_info for files in the specified state
        """
        result = {}
        
        for file_id, file_info in self.manifest["files"].items():
            if file_info.get("state") == state:
                result[file_id] = file_info
        
        return result
    
    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate the manifest structure.

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []

        # Check required top-level keys
        required_keys = ["manifest_version", "created_at", "operations", "files"]
        for key in required_keys:
            if key not in self.manifest:
                errors.append(f"Missing required key: {key}")

        # Check manifest version (support v1, v2, and v3)
        manifest_version = self.manifest.get("manifest_version")
        if manifest_version not in [1, 2, 3]:
            errors.append(f"Unsupported manifest version: {manifest_version}")

        # Validate v3-specific fields if present
        if manifest_version == 3:
            if "manifest_id" not in self.manifest:
                errors.append("v3 manifest missing required 'manifest_id' field")
            if "parent_ids" not in self.manifest:
                errors.append("v3 manifest missing required 'parent_ids' field")
            elif not isinstance(self.manifest["parent_ids"], list):
                errors.append("'parent_ids' must be an array")

        # Validate operations
        for i, operation in enumerate(self.manifest.get("operations", [])):
            if "type" not in operation:
                errors.append(f"Operation {i} is missing required 'type' field")
            if "timestamp" not in operation:
                errors.append(f"Operation {i} is missing required 'timestamp' field")

        # Validate files
        for file_id, file_info in self.manifest.get("files", {}).items():
            if "source_path" not in file_info:
                errors.append(f"File {file_id} is missing required 'source_path' field")
            if "destination_path" not in file_info:
                errors.append(f"File {file_id} is missing required 'destination_path' field")

        return len(errors) == 0, errors

    # =========================================================================
    # DAG/Lineage Methods (v3.0)
    # =========================================================================

    def get_manifest_id(self) -> str:
        """
        Get the unique ID of this manifest.

        Returns:
            Manifest ID string
        """
        return self.manifest.get("manifest_id", "")

    def set_parent(self, parent_manifest_id: str) -> None:
        """
        Set a single parent manifest for this manifest.

        This is the common case for 0.7.x (linear history).
        For merge operations (0.8.x+), use add_parent() instead.

        Args:
            parent_manifest_id: ID of the parent manifest
        """
        self.manifest["parent_ids"] = [parent_manifest_id]
        self._update_lineage()

    def add_parent(self, parent_manifest_id: str) -> None:
        """
        Add a parent manifest to this manifest's parent list.

        Used for merge operations where a manifest has multiple parents.
        For single-parent operations, use set_parent() instead.

        Args:
            parent_manifest_id: ID of the parent manifest to add
        """
        if "parent_ids" not in self.manifest:
            self.manifest["parent_ids"] = []
        if parent_manifest_id not in self.manifest["parent_ids"]:
            self.manifest["parent_ids"].append(parent_manifest_id)
        self._update_lineage()

    def get_parent_ids(self) -> List[str]:
        """
        Get the list of parent manifest IDs.

        Returns:
            List of parent manifest IDs (empty if this is a root manifest)
        """
        return self.manifest.get("parent_ids", [])

    def has_parents(self) -> bool:
        """
        Check if this manifest has any parents.

        Returns:
            True if this manifest has at least one parent
        """
        return len(self.get_parent_ids()) > 0

    def is_merge(self) -> bool:
        """
        Check if this manifest is a merge (has multiple parents).

        Returns:
            True if this manifest has more than one parent
        """
        return len(self.get_parent_ids()) > 1

    def get_lineage(self) -> Dict[str, Any]:
        """
        Get lineage information for this manifest.

        Returns:
            Dictionary with root_id, depth, and is_merge fields
        """
        return self.manifest.get("lineage", {
            "root_id": self.get_manifest_id(),
            "depth": 0,
            "is_merge": False
        })

    def _update_lineage(self) -> None:
        """
        Update lineage helper fields based on current parent_ids.

        Note: In 0.7.x, we don't traverse the full DAG to compute
        accurate depth/root_id. That's a 0.8.x enhancement.
        """
        parent_ids = self.get_parent_ids()
        self.manifest["lineage"] = {
            "root_id": self.manifest.get("lineage", {}).get("root_id"),
            "depth": len(parent_ids),  # Simplified for now
            "is_merge": len(parent_ids) > 1
        }

    def incorporate_file(
        self,
        file_id: str,
        source_path: str,
        dest_path: str,
        hashes: Dict[str, str],
        original_manifest_id: Optional[str] = None,
        original_source_path: Optional[str] = None
    ) -> str:
        """
        Incorporate an existing file into this manifest without copying.

        Used for identical files that already exist at the destination.
        The file is added to the manifest with its current hash values
        and optionally linked to its original manifest/source.

        Args:
            file_id: ID for the file entry (typically dest_path)
            source_path: Current source path (what user specified)
            dest_path: Destination path where file already exists
            hashes: Hash values of the file (must match)
            original_manifest_id: ID of manifest where file was first tracked
            original_source_path: Original source path from first operation

        Returns:
            The file ID used to reference this file
        """
        # Create file entry
        file_entry = {
            "source_path": source_path,
            "destination_path": dest_path,
            "added_at": datetime.datetime.now().isoformat(),
            "incorporated": True,  # Flag indicating not copied, but incorporated
            "hashes": hashes,
            "history": []
        }

        # Add lineage info if available
        if original_manifest_id or original_source_path:
            file_entry["lineage"] = {
                "original_manifest_id": original_manifest_id,
                "original_source_path": original_source_path
            }

        self.manifest["files"][file_id] = file_entry
        return file_id


def calculate_file_hash(
    file_path: Union[str, Path],
    algorithms: List[str] = None,
    buffer_size: int = 65536,
    manifest: Optional['PreserveManifest'] = None,
    progress_callback: Optional[callable] = None
) -> Dict[str, str]:
    """
    Calculate hash values for a file using multiple algorithms.

    This is the main implementation in preservelib.

    Args:
        file_path: Path to the file
        algorithms: List of hash algorithms to use (default: ["SHA256"])
        buffer_size: Size of the buffer for reading the file in chunks
        manifest: Optional manifest to record hash calculations
        progress_callback: Optional callback for progress reporting

    Returns:
        Dictionary mapping algorithm names to hash values
    """
    if algorithms is None:
        algorithms = ["SHA256"]

    path = Path(file_path)
    if not path.exists() or not path.is_file():
        logger.warning(f"Cannot calculate hash for non-existent file: {path}")
        return {}

    result = {}
    hash_objects = {}

    # Report progress if callback provided
    if progress_callback:
        progress_callback(f"Calculating hash for {file_path}")

    # Initialize hash objects
    for algorithm in algorithms:
        alg = algorithm.lower()
        if alg == "md5":
            hash_objects[algorithm] = hashlib.md5()
        elif alg == "sha1":
            hash_objects[algorithm] = hashlib.sha1()
        elif alg == "sha256":
            hash_objects[algorithm] = hashlib.sha256()
        elif alg == "sha512":
            hash_objects[algorithm] = hashlib.sha512()
        else:
            logger.warning(f"Unsupported hash algorithm: {algorithm}")
            continue

    try:
        # Read file in chunks and update all hash objects
        with open(path, 'rb') as f:
            while chunk := f.read(buffer_size):
                for hash_obj in hash_objects.values():
                    hash_obj.update(chunk)

        # Get hash values
        for algorithm, hash_obj in hash_objects.items():
            result[algorithm] = hash_obj.hexdigest()

    except Exception as e:
        logger.error(f"Error calculating hash for {path}: {e}")

    # Record in manifest if provided (preserve-specific feature)
    if manifest and result:
        try:
            # This is a preserve-specific feature
            logger.debug(f"Recording hash calculation in manifest for {file_path}")
        except Exception as e:
            logger.warning(f"Failed to record hash in manifest: {e}")

    return result


def verify_file_hash(
    file_path: Union[str, Path],
    expected_hashes: Dict[str, str],
    manifest: Optional['PreserveManifest'] = None
) -> Tuple[bool, Dict[str, Tuple[bool, str, str]]]:
    """
    Verify a file against expected hash values.

    This is the main implementation in preservelib.

    Args:
        file_path: Path to the file
        expected_hashes: Dictionary mapping algorithm names to expected hash values
        manifest: Optional manifest to record verification results

    Returns:
        Tuple of (overall_success, details) where details is a dictionary mapping
        algorithm names to tuples of (success, expected_hash, actual_hash)
    """
    if not expected_hashes:
        logger.warning(f"No expected hashes provided for {file_path}")
        return False, {}

    # Calculate actual hashes
    actual_hashes = calculate_file_hash(file_path, list(expected_hashes.keys()))

    if not actual_hashes:
        logger.warning(f"Failed to calculate hashes for {file_path}")
        return False, {}

    # Compare hashes
    results = {}
    all_match = True

    for algorithm, expected in expected_hashes.items():
        if algorithm not in actual_hashes:
            results[algorithm] = (False, expected, None)
            all_match = False
        else:
            actual = actual_hashes[algorithm]
            match = expected.lower() == actual.lower()
            results[algorithm] = (match, expected, actual)
            if not match:
                all_match = False

    # Record in manifest if provided (preserve-specific feature)
    if manifest:
        try:
            logger.debug(f"Recording verification result in manifest for {file_path}: {all_match}")
        except Exception as e:
            logger.warning(f"Failed to record verification in manifest: {e}")

    return all_match, results


def find_available_manifests(source_path: Union[str, Path]) -> List[Tuple[int, Path, Optional[str]]]:
    """Find all manifest files with their metadata.

    Returns a list of tuples: (number, path, description)
    where number is 0 for unnumbered manifest, or the actual number for numbered ones.

    Args:
        source_path: Directory to search for manifests

    Returns:
        List of tuples containing (manifest_number, manifest_path, description)
        Sorted by number (0 for single manifest comes first, then numbered)
    """
    import re

    manifests = []
    source = Path(source_path)

    # Check for single manifest
    single = source / 'preserve_manifest.json'
    if single.exists():
        manifests.append((0, single, None))

    # Find numbered manifests
    pattern = re.compile(r'preserve_manifest_(\d{3})(?:__(.*))?\.json')
    for file in source.glob('preserve_manifest_*.json'):
        match = pattern.match(file.name)
        if match:
            num = int(match.group(1))
            desc = match.group(2) if match.group(2) else None
            manifests.append((num, file, desc))

    # Sort by number (0 for single manifest comes first, then numbered)
    return sorted(manifests, key=lambda x: x[0])


def create_manifest_for_path(path: Union[str, Path], dest_dir: Union[str, Path],
                           recursive: bool = True, operation_type: str = "COPY",
                           command_line: Optional[str] = None,
                           options: Optional[Dict[str, Any]] = None) -> PreserveManifest:
    """
    Create a manifest for files in a directory.
    
    Args:
        path: Source path (file or directory)
        dest_dir: Destination directory
        recursive: Whether to recurse into subdirectories
        operation_type: Type of operation (COPY, MOVE, etc.)
        command_line: Original command line (optional)
        options: Additional options (optional)
        
    Returns:
        Manifest object with file entries
    """
    manifest = PreserveManifest()
    
    # Add operation
    op_id = manifest.add_operation(
        operation_type=operation_type,
        source_path=str(path),
        destination_path=str(dest_dir),
        options=options,
        command_line=command_line
    )
    
    # Process files
    source_path = Path(path)
    dest_path = Path(dest_dir)
    
    if source_path.is_file():
        # Single file
        dest_file = dest_path / source_path.name
        file_id = manifest.add_file(
            source_path=str(source_path),
            destination_path=str(dest_file),
            operation_id=op_id
        )
    elif source_path.is_dir():
        # Directory
        _process_directory_for_manifest(
            manifest=manifest,
            source_dir=source_path,
            dest_dir=dest_path,
            recursive=recursive,
            operation_id=op_id
        )
    else:
        logger.warning(f"Source path does not exist: {source_path}")
    
    return manifest


def _process_directory_for_manifest(manifest: PreserveManifest, source_dir: Path, dest_dir: Path,
                                  recursive: bool, operation_id: int) -> None:
    """
    Process a directory for manifest creation.
    
    Args:
        manifest: Manifest to update
        source_dir: Source directory
        dest_dir: Destination directory
        recursive: Whether to recurse into subdirectories
        operation_id: Operation ID to associate with files
    """
    # Process files in directory
    for item in source_dir.iterdir():
        if item.is_file():
            # Add file to manifest
            dest_file = dest_dir / item.relative_to(source_dir)
            manifest.add_file(
                source_path=str(item),
                destination_path=str(dest_file),
                operation_id=operation_id
            )
        elif item.is_dir() and recursive:
            # Create destination subdirectory
            dest_subdir = dest_dir / item.relative_to(source_dir)
            
            # Recurse into subdirectory
            _process_directory_for_manifest(
                manifest=manifest,
                source_dir=item,
                dest_dir=dest_subdir,
                recursive=recursive,
                operation_id=operation_id
            )


def extract_source_from_manifest(manifest: PreserveManifest) -> Optional[Path]:
    """
    Extract the source location from a manifest.

    Tries multiple strategies:
    1. Look for source_base in operations
    2. Find common prefix of all source_path entries
    3. Use parent of first source file as fallback

    Args:
        manifest: The manifest to extract source from

    Returns:
        Path to source location, or None if not found
    """
    # Handle both PreserveManifest objects and dict objects
    if isinstance(manifest, dict):
        manifest_data = manifest
    else:
        manifest_data = manifest.manifest

    # Strategy 1: Check for source_base in operations
    for op in manifest_data.get("operations", []):
        options = op.get("options", {})
        if "source_base" in options and options["source_base"]:
            source_base = Path(options["source_base"])
            logger.debug(f"Found source_base in manifest: {source_base}")
            return source_base

    # Strategy 2: Find common prefix of all source paths
    source_paths = []
    for file_info in manifest_data.get("files", {}).values():
        if "source_path" in file_info:
            source_paths.append(Path(file_info["source_path"]))

    if not source_paths:
        logger.debug("No source paths found in manifest")
        return None

    if len(source_paths) == 1:
        # Single file - return its parent directory
        return source_paths[0].parent

    try:
        # Find common path for multiple files
        import os
        common = os.path.commonpath([str(p) for p in source_paths])
        common_path = Path(common)
        logger.debug(f"Found common source prefix: {common_path}")
        return common_path
    except ValueError:
        # No common path (e.g., different drives on Windows)
        # Use parent of first file as best guess
        logger.debug("No common path found, using first file's parent")
        return source_paths[0].parent


def read_manifest(path: Union[str, Path]) -> Optional[PreserveManifest]:
    """
    Read a manifest from a file.

    Args:
        path: Path to the manifest file

    Returns:
        Manifest object, or None if the file does not exist or is invalid
    """
    try:
        manifest = PreserveManifest(path)
        valid, errors = manifest.validate()

        if not valid:
            logger.warning(f"Invalid manifest: {path}")
            for error in errors:
                logger.warning(f"  {error}")
            return None

        return manifest
    except Exception as e:
        logger.error(f"Error reading manifest: {e}")
        return None
