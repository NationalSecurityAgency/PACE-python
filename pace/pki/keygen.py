## **************
##  Copyright 2015 MIT Lincoln Laboratory
##  Project: PACE
##  Authors: ES
##  Description: Key generation, wrapping, and storage
##  Modifications:
##  Date         Name  Modification
##  ----         ----  ------------
##  30 July 2015 ES    Original file
## **************

import os
import sys
this_dir = os.path.dirname(os.path.dirname(__file__))
base_dir = os.path.join(this_dir, '../..')
sys.path.append(base_dir)
import math
import ConfigParser
import struct
import hmac
from hashlib import sha1

from Crypto import Random
from Crypto.PublicKey import RSA
import pace.pki.key_wrap_utils as utils
from pace.pki.keystore import KeyInfo

class KeyGen(object):
    def __init__(self, msk):
        """ Initializes key generator with master secret key.
        
        Arguments:
        msk (string) - the master secret key for the key generator. This must be
            chosen at random and at least the output length of the hash function
            used for key generation - in the case of SHA-1, 20 bytes.
        """

        self._msk = msk

    def _generate_key(self, attr, vers, metadata, keylen):
        """ Generates a key corresponding to the specified attribute, version,
            metadata, and key length. The key is generated by applying a 
            keyed-hash message authentication code (HMAC) to the inputs, in the
            manner specified by the ''extract'' stage of the HMAC-based key 
            derivation function HKDF, using the key generator's master secret 
            key as the secret HMAC key. The key length is included the input to
            the HMAC so that keys are unpredictable even if given keys of 
            different lengths for the same attribute, version, and metadata. 
            The key generation function is deterministic, so keys 
            can be regenerated.

            Arguments:
            attr (string) - attribute for which the key is to be generated
            vers (string) - version for which the key is to be generated
            metadata (string) - metadata about the key (e.g., the mode of 
                operation with which it is to be used)
            keylen (integer) - length of key to be generated, in bytes; 
                non-negative, no more than 255 times the output length of the 
                hash function (the output length of SHA-1 is 20 bytes)

            Note: attr, vers, and metadata strings must not contain the '|' 
            character.
            
            Returns:
            A key for the specified attribute, version, metadata, and key 
            length.
        """

        h = hmac.new(self._msk, digestmod=sha1)
        if (keylen < 0):
            raise ValueError('Key length must be non-negative')
        num_blocks = int(math.ceil((keylen*1.0)/h.digest_size))
        #Include key length in info so that keys are unpredictable even if 
        #given keys for different lengths for the same attribute, version, and 
        #metadata
        key_info = '|'.join([attr, str(vers), metadata, str(keylen)])
        key = ''
        block = ''
        for i in xrange(num_blocks):
            #Create a one-byte representation of the block number
            block_num = bytes(bytearray(struct.pack('>i', i+1)))[-1]
            h = hmac.new(self._msk, block + key_info + block_num, sha1)
            block = h.digest()
            key += block
        return key[:keylen]

    def initialize_users(self, users, keystore):
        """ Generates users' keys, wraps them with their public keys, and 
            stores the keywraps and associated info in the key store.
            
            Arguments:
            users ({string: (_RSAobj, [(string, string, string, integer)])}) - 
                a dictionary mapping user IDs to (RSA_pk, info) tuples, where
                RSA_pk is the user's RSA public key, and info is a list of 
                (attr, vers, metadata, keylen) tuples describing the attribute, 
                version, metadata, and key length (in bytes) of the keys to 
                generate, wrap, and store.
                Note: attr, vers, and metadata strings must not contain the '|' 
                character.
            keystore (AbstractKeyStore) - the key store to be written to
        """
        for userid, (RSA_pk, info) in users.iteritems():
            keywraps = []
            for attr, vers, metadata, keylen in info:
                sk = self._generate_key(attr, vers, metadata, keylen)
                keywrap = utils.wrap_key(sk, RSA_pk)
                keywraps.append(KeyInfo(attr, vers, metadata, keywrap, keylen))
            keystore.batch_insert(userid, keywraps)

    def init_from_file(self, user_file, keystore):
        """ Given a user configuration file, generates users' keys, wraps them 
            with their public keys, and stores the keywraps and associated info
            in the key store.
            
            Arguments:
            user_file (string or [string]): a user config file name or list of 
                file names. 
                Each file should consist of sections with a user ID as the 
                section header followed by 'public_key' and 'key_info' options.
                The 'public_key' value should be the name of a file containing 
                an exported RSA public key.
                The 'key_info' value should be a newline-separated list of 
                pipe-delimited strings specifying an attribute, version, 
                metadata, and key length (in bytes). 
                The attribute, version, and metadata must not contain the '|' 
                character.
                See user_info.cfg for an example.
                #TODO: allow pipe character within a quoted string
            keystore (AbstractKeyStore) - the key store to be written to

            Raises an IOError if any of the public key files listed within 
            the config file cannot be opened.
        """
        users = self.file_to_dict(user_file)
        self.initialize_users(users, keystore)

    @staticmethod
    def file_to_dict(user_file):
        """ Constructs a dictionary mapping users to public keys and attribute 
            key information from a user configuration file.

            Arguments:
            user_file (string or [string]): a user config file name or list of 
                file names. 
                Each file should consist of sections with a user ID as the 
                section header followed by 'public_key' and 'key_info' options.
                The 'public_key' value should be the name of a file containing 
                an exported RSA public key.
                The 'key_info' value should be a newline-separated list of 
                pipe-delimited strings specifying an attribute, version, 
                metadata, and key length (in bytes). 
                The attribute, version, and metadata must not contain the '|' 
                character.
                See user_info.cfg for an example.
                #TODO: allow pipe character within a quoted string
            
            Returns:
            A dictionary of type 
            {string: (RSA._RSAobj, [(string, string, string, integer)])}) 
            mapping user IDs to (RSA_pk, info) tuples, where RSA_pk is the 
            user's RSA public key, and info is a list of (attr, vers, metadata,
            keylen) tuples describing the attribute, version, metadata, and key 
            length (in bytes) of the user's keys.

            Raises an IOError if any of the public key files listed within 
            the config file cannot be opened.
        """
        abs_path = os.path.dirname(user_file)
        user_config = ConfigParser.ConfigParser()
        try:
            user_config.read(user_file)
        except IOError as e:
            print 'Error opening config file:', e
            raise e
        users = {}
        userids = user_config.sections()
        for userid in userids:
            try:
                f = open(abs_path+'/'+user_config.get(userid, 'public_key'), 'r')
            except IOError as e:
                print 'Error opening user', userid +'\'s', 'public key file:'
                print e
                raise e
            RSA_pk = RSA.importKey(f.read())
            f.close()
            info = []
            key_infos = user_config.get(userid, 'key_info').splitlines()
            for key_info in key_infos:
                attr, vers, metadata, keylen = key_info.split('|')
                info.append((attr, int(vers), metadata, int(keylen)))
            users[userid] = (RSA_pk, info)
        return users

    def revoke(self, userid, attr, keystore, attr_user_map, user_attr_map, 
               user_pks, metas_keylens={}):
        """ Revoke an attribute from a user. Specifically, delete all of the 
            user's keys for that attribute for all supported metadatas, generate
            new keys for all supported metadatas, wrap them for all other users
            with that attribute, and insert them into the keystore. Optionally,
            new keys can have new key lengths. If the user to revoke does not 
            have the specified attribute, this function does nothing.

            Arguments:
            userid (string) - the ID of the user whose keys to revoke
            attr (string) - the attribute of the keys to revoke
            keystore (AbstractKeyStore) - the key store to which to write the 
                new keywraps for all other users with the given attribute
            attr_user_map (AbstractAttrUserMap) - an attribute-to-user map 
                that can return a list of all users with the given attribute
            user_attr_map (AbstractUserAttrMap) - a user-to-attribute map that 
                can return a list of all attributes of a given user
            user_pks ({string: RSA._RSA_obj}) - a dictionary that maps user IDs
                to users' RSA public keys
            metas_keylens (optional {string: int}) - an optional dictionary that
                maps metadatas to new key lengths. For any metadata not in the 
                dictionary, the new key will have the same length as the current
                key.
        """

        #If revoked user does not have the specified attribute, do nothing
        cur_users = attr_user_map.users_by_attribute(attr)
        if userid not in cur_users:
            return
        
        #Delete revoked user/attribute from maps
        attr_user_map.delete_user(attr, userid)
        user_attr_map.delete_attr(userid, attr)

        metas = keystore.get_metadatas(userid, attr)
        new_keys = {}

        #For each supported metadata, generate a new attribute key and delete 
        #revoked user's keys
        for meta in metas:
            cur_info = keystore.retrieve_latest_version(userid, meta, attr)
            new_vers = cur_info.vers + 1
            if meta in metas_keylens:
                new_keylen = metas_keylens[meta]
            else:
                new_keylen = cur_info.keylen
            new_key = self._generate_key(attr, new_vers, meta, new_keylen)
            new_keys[meta] = new_key
            keystore.remove_revoked_keys(userid, meta, attr)
        
        #Wrap newly generated keys for other users and add to keystore
        cur_users.remove(userid)
        for user in cur_users:
            for meta in keystore.get_metadatas(user, attr):
                if meta in new_keys:
                    sk = new_keys[meta]
                    RSA_pk = user_pks[user]
                    keywrap = utils.wrap_key(sk, RSA_pk)
                    keystore.insert(user, KeyInfo(attr, new_vers, meta, keywrap,
                                                  new_keylen))

    def revoke_all_attrs(self, userid, keystore, attr_user_map, user_attr_map, 
                         user_pks, metas_keylens={}):
        """ Revoke all attributes of a user. Specifically, delete all of the 
            user's keys for all of their attributes and supported metadatas,
            generate new keys for all of those attributes and metadatas, wrap 
            them for all other users with those attributes, and insert them into
            the keystore. Optionally, new keys can have new key lengths.

            Arguments:
            userid (string) - the ID of the user whose keys to revoke
            keystore (AbstractKeyStore) - the key store to which to write the 
                new keywraps for all other users with the given attribute
            attr_user_map (AbstractAttrUserMap) - an attribute-to-user map 
                that can return a list of all users with the given attribute
            user_attr_map (AbstractUserAttrMap) - a user-to-attribute map that 
                can return a list of all attributes of a given user
            user_pks ({string: RSA._RSA_obj}) - a dictionary that maps user IDs
                to users' RSA public keys
            metas_keylens (optional {string: int}) - an optional dictionary that
                maps metadatas to new key lengths. All of the new attribute keys
                for a given metadata in the dictionary will have the same new 
                length. For any metadata not in the dictionary, new keys will 
                have the same length as the current key.
        """

        attrs = user_attr_map.attributes_by_user(userid)
        for attr in attrs:
            self.revoke(userid, attr, keystore, attr_user_map, user_attr_map, 
                        user_pks, metas_keylens)
